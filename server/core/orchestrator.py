import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator
from .llm_connector import LLMConnector, _strip_thought_blocks


class Orchestrator:
    def __init__(self):
        self._context: list[dict] = []

    def reset(self):
        self._context = []
        # 다음 process() 호출에서 시스템 프롬프트가 다시 삽입됨

    _SYSTEM_PROMPT = """\
당신은 로컬 AI 어시스턴트입니다. 사용자의 요청에 맞는 도구(tool/skill)를 적극적으로 호출하세요.

## /명령어 규칙
사용자가 `/skill_name` 형식으로 입력하면 해당 도구를 **즉시 호출**하세요.
- `/wiki_ingest sources/foo.md` → `wiki_ingest` 도구를 `target="sources/foo.md"`로 호출
- `/wiki_query 검색어` → `wiki_query` 도구를 `question="검색어"`로 호출
- `/wiki_lint` → `wiki_lint` 도구 호출
- `/wiki_confluence_page <URL>` → `wiki_confluence_page` 도구를 `url="<URL>"`로 호출

## Wiki Ingest 워크플로우 — 반드시 따를 것
`wiki_ingest` 도구 결과에 `source_content` 필드가 있으면 **설명 없이 즉시** 다음을 수행하세요:
1. `source_content` 내용을 분석해 페이지 유형(concept/entity/process/summary) 결정
2. 아래 frontmatter를 포함한 한국어 마크다운 페이지 작성:
   ```
   ---
   title: 페이지 제목
   type: concept | entity | process | summary
   tags: [태그1, 태그2]
   source: 원본 파일명
   updated: 오늘 날짜(YYYY-MM-DD)
   ---
   ```
3. `wiki_write_page` 도구를 즉시 호출해 `wiki/summaries/` 또는 적절한 위치에 저장
4. 저장 후 결과를 사용자에게 보고

**중요: `source_content`를 받은 뒤 "분석하겠습니다", "저장하겠습니다" 같은 예고 텍스트를 출력하지 말고 바로 `wiki_write_page`를 호출하세요.**
"""

    # ── /command 파싱 ─────────────────────────────────────────────────────────

    @staticmethod
    def _looks_like_path(token: str) -> bool:
        """파일 경로처럼 생긴 토큰인지 확인 (슬래시·백슬래시 포함 또는 확장자 보유)"""
        return bool(token) and (
            "/" in token or "\\" in token
            or re.search(r"\.\w{1,5}$", token) is not None
        )

    @staticmethod
    def _looks_like_url(token: str) -> bool:
        return token.startswith("http://") or token.startswith("https://")

    @classmethod
    def _parse_slash_command(cls, text: str) -> tuple[str, dict] | None:
        """
        '/skill_name [args...]' 패턴을 파싱해 (skill_name, kwargs) 반환.
        패턴이 없으면 None 반환.
        """
        m = re.match(r"^/(\w+)\s*(.*)", text.strip(), re.DOTALL)
        if not m:
            return None
        cmd, rest = m.group(1), m.group(2).strip()
        tokens = rest.split()
        first = tokens[0] if tokens else ""

        if cmd == "wiki_ingest":
            # 경로처럼 생긴 토큰이 있을 때만 target 지정, 아니면 목록 조회
            target = first if cls._looks_like_path(first) else None
            kwargs = {"target": target} if target else {}
        elif cmd == "wiki_query":
            kwargs = {"question": rest} if rest else {}
        elif cmd in ("wiki_lint", "wiki_list_pages"):
            kwargs = {}
        elif cmd == "wiki_read_page":
            kwargs = {"path": first} if cls._looks_like_path(first) else {}
        elif cmd in ("wiki_confluence_page", "wiki_confluence_tree"):
            kwargs = {"url": first} if cls._looks_like_url(first) else {}
        else:
            return None  # 알 수 없는 /command → LLM에게 위임
        return cmd, kwargs

    async def _execute_slash(
        self, cmd: str, kwargs: dict, skill_registry
    ) -> tuple[dict, str]:
        """
        슬래시 커맨드 스킬을 직접 실행하고 (result, tool_id) 반환.
        context에 assistant tool_call + tool result 메시지를 추가한다.
        """
        tool_id = f"slash_{uuid.uuid4().hex[:8]}"
        self._context.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": tool_id,
                "type": "function",
                "function": {"name": cmd, "arguments": json.dumps(kwargs, ensure_ascii=False)},
            }],
        })
        skill = skill_registry.get(cmd)
        if skill is None:
            result = {"error": f"스킬 '{cmd}'를 찾을 수 없습니다. 설정(⚙)에서 LLM Wiki 경로를 저장했는지 확인하세요."}
        else:
            try:
                result = await skill.run(**kwargs)
            except Exception as e:
                result = {"error": str(e)}

        self._context.append({
            "role": "tool",
            "tool_call_id": tool_id,
            "content": json.dumps(result, ensure_ascii=False),
        })
        return result, tool_id

    # ── public entry point ────────────────────────────────────────────────────

    async def process(
        self,
        user_message: str,
        endpoint_url: str,
        api_key: str,
        model: str,
        skill_registry,
        stream: bool = False,
        image: str | None = None,
    ):
        # 첫 메시지일 때 시스템 프롬프트 삽입
        if not self._context:
            self._context.append({"role": "system", "content": self._SYSTEM_PROMPT})

        if image:
            content: list | str = [
                {"type": "text", "text": user_message or "이 이미지를 분석해줘."},
                {"type": "image_url", "image_url": {"url": image}},
            ]
            logging.info("[Orchestrator] Multimodal message (image attached)")
        else:
            content = user_message

        self._context.append({"role": "user", "content": content})
        connector = LLMConnector(endpoint_url, api_key)
        tools = None if image else (skill_registry.to_tools() or None)

        # /command 패턴이면 LLM 없이 직접 스킬 실행
        if not image:
            parsed = self._parse_slash_command(user_message)
            if parsed:
                cmd, kwargs = parsed
                logging.info(f"[Slash] {cmd}({kwargs})")
                result, _ = await self._execute_slash(cmd, kwargs, skill_registry)

                if "error" in result:
                    if stream:
                        async def _err():
                            yield f"오류: {result['error']}"
                        return _err()
                    return f"오류: {result['error']}"

                if cmd == "wiki_ingest" and "source_content" in result:
                    # LLM에게 tool 호출을 시키지 않고 오케스트레이터가 파이프라인 직접 처리
                    if stream:
                        return self._ingest_pipeline_stream(result, connector, model, skill_registry)
                    else:
                        return await self._ingest_pipeline_blocking(result, connector, model, skill_registry)

                if cmd == "wiki_query":
                    if stream:
                        return self._query_pipeline_stream(result, connector, model)
                    else:
                        return await self._query_pipeline_blocking(result, connector, model)

                # 그 외 slash 결과는 LLM이 자연어로 정리 (tool 없이)
                self._context.append({
                    "role": "user",
                    "content": "위 결과를 사용자에게 자연어로 간략히 요약해줘."
                })

        if stream:
            return self._stream_loop(connector, model, tools, skill_registry)
        else:
            return await self._blocking_loop(connector, model, tools, skill_registry)

    # ── Wiki Ingest 전용 파이프라인 ───────────────────────────────────────────

    def _build_ingest_prompt(self, source_path: str, source_content: str) -> str:
        today = datetime.now().strftime("%Y-%m-%d")
        return (
            f"아래 소스 파일을 분석해 한국어 위키 페이지를 작성하세요.\n"
            f"소스 파일: {source_path}\n\n"
            f"[소스 내용]\n{source_content}\n\n"
            f"반드시 아래 형식으로만 출력하세요 (다른 설명 없이 마크다운만):\n\n"
            f"---\n"
            f"title: (페이지 제목)\n"
            f"type: summary\n"
            f"tags: [태그1, 태그2]\n"
            f"source: {source_path}\n"
            f"updated: {today}\n"
            f"---\n\n"
            f"(한국어 내용 — 핵심 개념, 구성 요소, 절차 등 구조적으로 작성)\n\n"
            f"## 관련 페이지\n"
            f"- [[관련 페이지명]]\n"
        )

    @staticmethod
    def _parse_frontmatter(content: str) -> dict:
        """마크다운 frontmatter에서 title/type 추출"""
        m = re.search(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if not m:
            return {}
        fm: dict = {}
        for line in m.group(1).splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                fm[k.strip()] = v.strip()
        return fm

    @staticmethod
    def _update_log(wiki_path: Path, wiki_file: str, source_path: str) -> None:
        """log.md에 오늘 날짜 항목 추가 (추가 전용)"""
        log_path = wiki_path / "log.md"
        today = datetime.now().strftime("%Y-%m-%d")
        entry = f"- `{wiki_file}` 생성: `{source_path}` 변환\n"

        if not log_path.exists():
            log_path.write_text(f"# 작업 로그\n\n---\n\n## {today}\n\n{entry}", encoding="utf-8")
            return

        text = log_path.read_text(encoding="utf-8")
        today_header = f"## {today}"
        if today_header in text:
            # 오늘 날짜 섹션이 있으면 그 아래에 추가
            text = text.replace(today_header, f"{today_header}\n\n{entry}", 1)
            # 중복 빈 줄 정리
            text = re.sub(r"\n{3,}", "\n\n", text)
        else:
            text = text.rstrip() + f"\n\n---\n\n## {today}\n\n{entry}"
        log_path.write_text(text, encoding="utf-8")

    @staticmethod
    def _update_index(wiki_path: Path, wiki_file: str, title: str, page_type: str) -> None:
        """index.md의 해당 섹션에 페이지 추가 및 통계 갱신"""
        index_path = wiki_path / "index.md"
        if not index_path.exists():
            return

        section_map = {
            "concept": "## 개념 (Concepts)",
            "entity":  "## 엔티티 (Entities)",
            "process": "## 프로세스 (Processes)",
            "summary": "## 요약 (Summaries)",
        }
        section_header = section_map.get(page_type, "## 요약 (Summaries)")
        stem = Path(wiki_file).stem
        row = f"| [[{stem}]] | {title} |"

        text = index_path.read_text(encoding="utf-8")

        # 이미 등록된 페이지면 스킵
        if stem in text:
            return

        # 해당 섹션의 "_아직 없음._" 문구를 테이블로 교체하거나 행 추가
        placeholder = "_아직 없음._"
        table_header = "| 파일 | 설명 |\n|------|------|"

        if section_header in text:
            idx = text.index(section_header)
            # 섹션 내 placeholder 교체
            section_text = text[idx:]
            if placeholder in section_text:
                text = text[:idx] + section_text.replace(
                    placeholder, f"{table_header}\n{row}", 1
                )
            else:
                # 기존 테이블 끝에 행 추가 (다음 ## 전에)
                next_section = re.search(r"\n## ", text[idx + len(section_header):])
                if next_section:
                    insert_pos = idx + len(section_header) + next_section.start()
                    text = text[:insert_pos].rstrip() + f"\n{row}\n\n" + text[insert_pos:]
                else:
                    text = text.rstrip() + f"\n{row}\n"

        # 통계 업데이트
        total = len(list((wiki_path / "wiki").rglob("*.md")))
        today = datetime.now().strftime("%Y-%m-%d")
        text = re.sub(r"- 총 페이지 수: \d+", f"- 총 페이지 수: {total}", text)
        text = re.sub(r"- 마지막 업데이트: .+", f"- 마지막 업데이트: {today}", text)

        # 처리된 소스 수 업데이트
        summaries_dir = wiki_path / "wiki" / "summaries"
        processed = len(list(summaries_dir.rglob("*.md"))) if summaries_dir.exists() else 0
        text = re.sub(r"- 처리된 소스 수: \d+", f"- 처리된 소스 수: {processed}", text)

        index_path.write_text(text, encoding="utf-8")

    async def _ingest_pipeline_stream(self, ingest_result: dict, connector: LLMConnector, model: str, skill_registry):
        source_path = ingest_result["source_path"]
        source_content = ingest_result["source_content"]
        filename = Path(source_path).stem

        prompt = self._build_ingest_prompt(source_path, source_content)
        gen_context = self._context + [{"role": "user", "content": prompt}]

        yield f"\n📝 `{source_path}` → 위키 페이지 생성 중...\n\n"

        generated = ""
        async for event in connector.stream_tokens(messages=gen_context, model=model, tools=None):
            if event["type"] == "content":
                token = event["value"]
                generated += token
                yield token

        generated = _strip_thought_blocks(generated).strip()

        # 오케스트레이터가 직접 wiki_write_page 호출
        wiki_file = f"wiki/summaries/{filename}.md"
        write_skill = skill_registry.get("wiki_write_page")
        if write_skill:
            write_result = await write_skill.run(path=wiki_file, content=generated)
            if write_result.get("success"):
                yield f"\n\n✅ 저장 완료: `{wiki_file}`"

                # log.md / index.md 업데이트
                fm = self._parse_frontmatter(generated)
                wiki_path = write_skill.wiki_path
                self._update_log(wiki_path, wiki_file, source_path)
                self._update_index(
                    wiki_path, wiki_file,
                    title=fm.get("title", filename),
                    page_type=fm.get("type", "summary"),
                )
                yield "\n📋 log.md · index.md 업데이트 완료"

                remaining = ingest_result.get("unprocessed_remaining", 0)
                if remaining > 0:
                    yield f"\n남은 미처리 파일: {remaining}개"
            else:
                yield f"\n\n❌ 저장 실패: {write_result.get('error', '알 수 없는 오류')}"
        else:
            yield f"\n\n⚠️ wiki_write_page 스킬을 찾을 수 없습니다."

        self._context.append({"role": "user", "content": prompt})
        self._context.append({"role": "assistant", "content": generated})

    # ── Wiki Query 전용 파이프라인 ────────────────────────────────────────────

    def _build_query_prompt(self, query_result: dict) -> str:
        question = query_result.get("question", "")
        pages = query_result.get("pages", [])
        keywords = query_result.get("keywords_used", [])
        if not pages:
            return (
                f"위키에서 '{question}' 검색 결과가 없습니다 (검색 키워드: {keywords}). "
                "사용자에게 관련 내용이 위키에 없다고 안내하고, 직접 아는 내용이 있으면 답변하세요."
            )
        pages_text = "\n\n".join(
            f"--- [{p['path']}] ---\n{p['content'][:3000]}" for p in pages
        )
        return (
            f"질문: {question}\n"
            f"검색 키워드: {keywords}\n\n"
            f"[관련 위키 페이지]\n{pages_text}\n\n"
            "위 위키 내용을 바탕으로 질문에 한국어로 답변하세요. "
            "출처 페이지를 명시하고, 위키에 없는 내용은 없다고 말하세요."
        )

    async def _query_pipeline_stream(self, query_result: dict, connector: LLMConnector, model: str):
        pages = query_result.get("pages", [])
        keywords = query_result.get("keywords_used", [])
        yield f"🔍 검색 키워드: `{'`, `'.join(keywords)}`  →  {len(pages)}개 페이지 발견\n\n"

        prompt = self._build_query_prompt(query_result)
        gen_context = self._context + [{"role": "user", "content": prompt}]

        generated = ""
        async for event in connector.stream_tokens(messages=gen_context, model=model, tools=None):
            if event["type"] == "content":
                token = event["value"]
                generated += token
                yield token

        self._context.append({"role": "user", "content": prompt})
        self._context.append({"role": "assistant", "content": _strip_thought_blocks(generated)})

    async def _query_pipeline_blocking(self, query_result: dict, connector: LLMConnector, model: str) -> str:
        prompt = self._build_query_prompt(query_result)
        gen_context = self._context + [{"role": "user", "content": prompt}]
        result = await connector.blocking_chat(messages=gen_context, model=model, tools=None)
        return _strip_thought_blocks(result["content"])

    # ── Wiki Ingest 전용 파이프라인 ───────────────────────────────────────────

    async def _ingest_pipeline_blocking(self, ingest_result: dict, connector: LLMConnector, model: str, skill_registry) -> str:
        source_path = ingest_result["source_path"]
        source_content = ingest_result["source_content"]
        filename = Path(source_path).stem

        prompt = self._build_ingest_prompt(source_path, source_content)
        gen_context = self._context + [{"role": "user", "content": prompt}]

        result = await connector.blocking_chat(messages=gen_context, model=model, tools=None)
        generated = _strip_thought_blocks(result["content"]).strip()

        wiki_file = f"wiki/summaries/{filename}.md"
        write_skill = skill_registry.get("wiki_write_page")
        if write_skill:
            write_result = await write_skill.run(path=wiki_file, content=generated)
            if write_result.get("success"):
                fm = self._parse_frontmatter(generated)
                wiki_path = write_skill.wiki_path
                self._update_log(wiki_path, wiki_file, source_path)
                self._update_index(wiki_path, wiki_file,
                                   title=fm.get("title", filename),
                                   page_type=fm.get("type", "summary"))
                return f"✅ 저장 완료: `{wiki_file}`\n📋 log.md · index.md 업데이트 완료\n\n{generated}"
            else:
                return f"❌ 저장 실패: {write_result.get('error')}"
        return generated

    # ── Non-streaming path (used after tool execution follow-ups) ────────────

    async def _blocking_loop(
        self, connector: LLMConnector, model: str, tools, skill_registry
    ) -> str:
        for _ in range(10):
            result = await connector.blocking_chat(
                messages=self._context, model=model, tools=tools
            )
            content = result["content"]
            tool_calls = result["tool_calls"]

            if not tool_calls:
                self._context.append({"role": "assistant", "content": content})
                return content

            self._context.append(self._build_assistant_msg(content, tool_calls))
            await self._execute_tools(tool_calls, skill_registry)

        return "최대 반복 횟수에 도달했습니다."

    # ── Streaming path ────────────────────────────────────────────────────────

    async def _stream_loop(
        self, connector: LLMConnector, model: str, tools, skill_registry
    ) -> AsyncGenerator[str, None]:
        """
        Streams LLM tokens to the client as they arrive.
        Tool calls are executed and the loop continues until the LLM returns no more tool calls.
        """
        for _ in range(10):
            accumulated_content = ""
            tool_calls = []

            # ── LLM에 보내는 전체 context 디버그 출력 ──────────────────────
            logging.info("=" * 80)
            logging.info("[LLM REQUEST] model=%s, tools=%d개", model, len(tools) if tools else 0)
            for i, msg in enumerate(self._context):
                role = msg.get("role", "?")
                content = msg.get("content", "")
                # content가 리스트(멀티모달)인 경우 요약
                if isinstance(content, list):
                    parts_summary = []
                    for part in content:
                        if part.get("type") == "text":
                            text_val = part.get("text", "")
                            parts_summary.append(f"text({len(text_val)}자): {text_val[:200]}")
                        elif part.get("type") == "image_url":
                            url = part.get("image_url", {}).get("url", "")
                            parts_summary.append(f"image({len(url)}bytes)")
                        else:
                            parts_summary.append(str(part)[:100])
                    content_display = " | ".join(parts_summary)
                elif isinstance(content, str):
                    content_display = content[:300]
                else:
                    content_display = str(content)[:300]
                # tool_calls 요약
                tc_info = ""
                if msg.get("tool_calls"):
                    tc_names = [tc["function"]["name"] for tc in msg["tool_calls"]]
                    tc_info = f" → tool_calls: {tc_names}"
                # tool_call_id 표시
                tcid = f" [tool_call_id={msg['tool_call_id']}]" if "tool_call_id" in msg else ""
                logging.info(
                    "[CTX %02d] role=%-10s%s%s | %s",
                    i, role, tcid, tc_info, content_display,
                )
            if tools:
                tool_names = [t["function"]["name"] for t in tools]
                logging.info("[TOOLS] %s", tool_names)
            logging.info("=" * 80)

            async for event in connector.stream_tokens(
                messages=self._context, model=model, tools=tools
            ):
                if event["type"] == "content":
                    token = event["value"]
                    accumulated_content += token
                    yield token
                elif event["type"] == "tool_calls":
                    tool_calls = event["value"]

            # context에 thought 잔해가 쌓이면 모델이 이를 보고 또 thinking → 무한루프
            clean_content = _strip_thought_blocks(accumulated_content)
            self._context.append(
                self._build_assistant_msg(clean_content, tool_calls)
            )

            if not tool_calls:
                return

            for tc in tool_calls:
                yield f"\n\n⚙ 스킬 실행 중: **{tc['name']}**...\n"
                logging.info(f"[Skill] Running {tc['name']} with {tc['arguments']}")

                skill = skill_registry.get(tc["name"])
                if skill is None:
                    tool_result = {"error": f"Skill '{tc['name']}' not found"}
                else:
                    try:
                        tool_result = await skill.run(**tc["arguments"])
                    except Exception as e:
                        tool_result = {"error": str(e)}

                # 이미지 수집: 단일(image_base64) 또는 다중(images_base64) 모두 지원
                images: list[str] = []
                single = tool_result.pop("image_base64", None)
                if single:
                    images.append(single)
                multi = tool_result.pop("images_base64", None)
                if multi:
                    images.extend(multi)

                # 채팅창에 이미지 표시
                labels = ["클릭 전", "클릭 후"] if len(images) >= 2 else ["스크린샷"] * len(images)
                for label, img_b64 in zip(labels, images):
                    yield f"\n**[{label}]**\n![{label}](data:image/jpeg;base64,{img_b64})\n"

                logging.info(f"[Skill] Result: {tool_result}")

                # 마지막 이미지를 LLM context에 포함 (분석용)
                if images:
                    content_parts: list = [
                        {"type": "text", "text": json.dumps(tool_result, ensure_ascii=False)}
                    ]
                    for img_b64 in images:
                        content_parts.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
                        })
                    self._context.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": content_parts,
                    })
                else:
                    self._context.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    })

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _build_assistant_msg(content: str, tool_calls: list) -> dict:
        msg: dict = {"role": "assistant", "content": content}
        if tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["arguments"]),
                    },
                }
                for tc in tool_calls
            ]
        return msg

    async def _execute_tools(self, tool_calls: list, skill_registry) -> None:
        for tc in tool_calls:
            skill = skill_registry.get(tc["name"])
            if skill is None:
                result = {"error": f"Skill '{tc['name']}' not found"}
            else:
                try:
                    result = await skill.run(**tc["arguments"])
                except Exception as e:
                    result = {"error": str(e)}

            # 이미지 수집: 단일(image_base64) 또는 다중(images_base64) 모두 지원
            images: list[str] = []
            single = result.pop("image_base64", None)
            if single:
                images.append(single)
            multi = result.pop("images_base64", None)
            if multi:
                images.extend(multi)

            if images:
                content_parts: list = [
                    {"type": "text", "text": json.dumps(result, ensure_ascii=False)}
                ]
                for img_b64 in images:
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
                    })
                self._context.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": content_parts,
                })
            else:
                self._context.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                })
