"""LLM Wiki 연동 스킬 — wiki 디렉토리를 검색·읽기·쓰기·품질점검합니다."""
import asyncio
import re
from pathlib import Path
from .skill_base import SkillBase


def _get_python_exe(wiki_path: Path) -> str:
    """scripts/config.yaml에서 python 실행 경로 읽기"""
    try:
        import yaml  # PyYAML
        config_path = wiki_path / "scripts" / "config.yaml"
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            return config.get("python", {}).get("executable", "python")
    except Exception:
        pass
    return "python"


async def _run_script(wiki_path: Path, script_name: str, *args: str) -> str:
    import os
    python_exe = _get_python_exe(wiki_path)
    script = wiki_path / "scripts" / script_name
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    proc = await asyncio.create_subprocess_exec(
        python_exe, "-X", "utf8", str(script), *args,
        cwd=str(wiki_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await proc.communicate()
    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")
    if err:
        out += f"\n[STDERR]\n{err}"
    return out


class WikiQuerySkill(SkillBase):
    name = "wiki_query"
    description = (
        "LLM Wiki에서 키워드로 관련 페이지를 검색하고 내용을 반환합니다. "
        "위키에서 정보를 찾거나 질문에 답할 때 사용하세요."
    )
    parameters = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "검색할 질문 또는 키워드 (공백으로 여러 단어 구분 가능)",
            }
        },
        "required": ["question"],
    }

    def __init__(self, wiki_path: str):
        self.wiki_path = Path(wiki_path)

    # 한국어 조사·어미·불용어 제거 패턴
    _KO_SUFFIXES = re.compile(
        r"(에서|에게|한테|으로|로부터|부터|까지|이라고|라고|이란|란|이나|나|"
        r"에도|에는|에만|에서는|은|는|이|가|을|를|와|과|의|에|로|도|만|"
        r"도록|하여|하고|하는|한|할|해|해서|해줘|알려줘|대해|관련|좀)$",
        re.UNICODE,
    )

    def _extract_keywords(self, question: str) -> list[str]:
        """질문 문장에서 검색 키워드 추출 (한국어 조사·불용어 제거)"""
        import re as _re
        stop = {"대해", "관련", "알려줘", "알려", "주세요", "해줘", "해주세요",
                "좀", "뭐야", "뭔가요", "어떤", "어떻게", "무엇", "찾아줘"}
        keywords = []
        for word in question.split():
            # 조사 접미사 반복 제거
            clean = self._KO_SUFFIXES.sub("", word)
            clean = self._KO_SUFFIXES.sub("", clean)  # 중첩 조사 처리
            if clean and clean not in stop and len(clean) > 1:
                keywords.append(clean.lower())
        # 원본 단어도 포함(영문/숫자 혼합어 보존)
        for word in question.split():
            w = word.lower()
            if w not in keywords and _re.search(r"[a-z0-9]", w):
                keywords.append(w)
        return list(dict.fromkeys(keywords))  # 중복 제거, 순서 보존

    def _search_wiki(self, keywords: list[str], top_n: int = 5) -> list[dict]:
        """wiki/ 디렉토리에서 키워드로 직접 검색"""
        wiki_dir = self.wiki_path / "wiki"
        if not wiki_dir.exists():
            return []
        results = []
        for md_file in wiki_dir.rglob("*.md"):
            content = md_file.read_text(encoding="utf-8")
            content_lower = content.lower()
            score = sum(content_lower.count(kw) for kw in keywords)
            if score > 0:
                results.append((score, str(md_file.relative_to(self.wiki_path)), content))
        results.sort(reverse=True)
        return [{"path": p, "content": c} for _, p, c in results[:top_n]]

    async def run(self, question: str) -> dict:
        keywords = self._extract_keywords(question)
        pages = self._search_wiki(keywords)
        return {
            "question": question,
            "keywords_used": keywords,
            "pages": pages,
            "found": len(pages) > 0,
        }


class WikiIngestSkill(SkillBase):
    name = "wiki_ingest"
    description = (
        "LLM Wiki의 sources/ 폴더에서 미처리 소스 파일 목록을 확인합니다. "
        "소스 파일을 위키 페이지로 변환하기 전 현황을 파악할 때 사용하세요."
    )
    parameters = {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "특정 파일명 필터 (선택사항). 생략하면 전체 소스 현황 반환.",
            }
        },
        "required": [],
    }

    def __init__(self, wiki_path: str):
        self.wiki_path = Path(wiki_path)

    async def run(self, target: str | None = None) -> dict:
        args = [target] if target else []
        output = await _run_script(self.wiki_path, "ingest.py", *args)

        # 미처리 파일 목록 계산
        sources_dir = self.wiki_path / "sources"
        unprocessed: list[str] = []
        if sources_dir.exists():
            wiki_dir = self.wiki_path / "wiki"
            summaries_dir = wiki_dir / "summaries"
            wiki_summaries = (
                {p.stem for p in summaries_dir.rglob("*.md")}
                if summaries_dir.exists()
                else set()
            )
            for f in sources_dir.rglob("*.md"):
                if "attachments" not in f.parts and f.stem not in wiki_summaries:
                    unprocessed.append(str(f.relative_to(self.wiki_path)))

        result: dict = {}

        # 읽을 파일 결정: target 지정 > 미처리 파일 자동 선택
        read_path: Path | None = None
        if target:
            candidates = [
                self.wiki_path / target,
                self.wiki_path / "sources" / target,
                self.wiki_path / target.replace("\\", "/"),
            ]
            for c in candidates:
                if c.exists():
                    read_path = c
                    break
            if read_path is None:
                return {"error": f"파일을 찾을 수 없습니다: {target}"}
        elif len(unprocessed) == 1:
            # 미처리 파일이 1개면 자동 선택
            read_path = self.wiki_path / unprocessed[0]
        elif len(unprocessed) > 1:
            # 여러 개면 목록만 반환하고 사용자에게 선택 요청
            result["unprocessed_files"] = unprocessed
            result["message"] = (
                f"미처리 소스 파일 {len(unprocessed)}개가 있습니다. "
                "변환할 파일 경로를 `/wiki_ingest <경로>`로 지정해 주세요."
            )
            return result
        else:
            return {"message": "변환할 미처리 소스 파일이 없습니다."}

        # 파일 내용 읽기
        content = read_path.read_text(encoding="utf-8")
        result["source_path"] = str(read_path.relative_to(self.wiki_path))
        result["source_content"] = content
        result["unprocessed_remaining"] = len(unprocessed) - 1 if not target else len(unprocessed)
        return result


class WikiLintSkill(SkillBase):
    name = "wiki_lint"
    description = (
        "LLM Wiki 품질을 점검합니다. "
        "미등록 페이지, 깨진 링크, 오래된 페이지를 탐지합니다."
    )
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, wiki_path: str):
        self.wiki_path = Path(wiki_path)

    async def run(self) -> dict:
        output = await _run_script(self.wiki_path, "lint.py")
        return {"output": output}


class WikiReadPageSkill(SkillBase):
    name = "wiki_read_page"
    description = (
        "LLM Wiki의 특정 페이지를 읽어 내용을 반환합니다. "
        "wiki/ 하위 상대 경로를 지정하세요."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "읽을 페이지 경로 (예: wiki/concepts/api-gateway.md)",
            }
        },
        "required": ["path"],
    }

    def __init__(self, wiki_path: str):
        self.wiki_path = Path(wiki_path)

    async def run(self, path: str) -> dict:
        full_path = self.wiki_path / path
        if not full_path.exists():
            return {"error": f"페이지를 찾을 수 없습니다: {path}"}
        content = full_path.read_text(encoding="utf-8")
        return {"path": path, "content": content}


class WikiWritePageSkill(SkillBase):
    name = "wiki_write_page"
    description = (
        "LLM Wiki에 새 페이지를 생성하거나 기존 페이지를 업데이트합니다. "
        "반드시 AGENTS.md의 frontmatter 형식(title, type, tags, updated)을 포함하세요."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "저장할 페이지 경로 (예: wiki/concepts/api-gateway.md)",
            },
            "content": {
                "type": "string",
                "description": "저장할 마크다운 내용 (frontmatter 포함)",
            },
        },
        "required": ["path", "content"],
    }

    def __init__(self, wiki_path: str):
        self.wiki_path = Path(wiki_path)

    async def run(self, path: str, content: str) -> dict:
        full_path = (self.wiki_path / path).resolve()
        wiki_root = self.wiki_path.resolve()

        # 경로 탈출 방지
        if not str(full_path).startswith(str(wiki_root)):
            return {"error": "위키 경로 외부에 쓸 수 없습니다."}
        if "sources" in Path(path).parts:
            return {"error": "sources/ 디렉토리는 읽기 전용입니다."}

        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        return {"success": True, "path": path}


class WikiListPagesSkill(SkillBase):
    name = "wiki_list_pages"
    description = (
        "LLM Wiki의 모든 페이지 목록과 index.md 요약을 반환합니다. "
        "위키 전체 구조를 파악하거나 탐색할 때 사용하세요."
    )
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, wiki_path: str):
        self.wiki_path = Path(wiki_path)

    async def run(self) -> dict:
        wiki_dir = self.wiki_path / "wiki"
        if not wiki_dir.exists():
            return {"pages": [], "message": "wiki/ 디렉토리가 없습니다."}

        pages = [
            str(f.relative_to(self.wiki_path))
            for f in sorted(wiki_dir.rglob("*.md"))
        ]

        index_path = self.wiki_path / "index.md"
        index_summary = (
            index_path.read_text(encoding="utf-8")[:3000]
            if index_path.exists()
            else None
        )

        return {
            "pages": pages,
            "total": len(pages),
            "index_summary": index_summary,
        }


class WikiConfluencePageSkill(SkillBase):
    name = "wiki_confluence_page"
    description = (
        "Confluence 단일 페이지를 마크다운으로 변환해 sources/에 저장합니다. "
        "페이지 URL을 인자로 전달하세요."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "변환할 Confluence 페이지 URL",
            }
        },
        "required": ["url"],
    }

    def __init__(self, wiki_path: str):
        self.wiki_path = Path(wiki_path)

    async def run(self, url: str) -> dict:
        output = await _run_script(self.wiki_path, "confluence_page.py", url)
        return {"output": output}


class WikiConfluenceTreeSkill(SkillBase):
    name = "wiki_confluence_tree"
    description = (
        "Confluence 페이지와 모든 하위 페이지를 재귀적으로 마크다운 변환해 sources/에 저장합니다. "
        "루트 페이지 URL을 인자로 전달하세요."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "변환할 Confluence 루트 페이지 URL",
            }
        },
        "required": ["url"],
    }

    def __init__(self, wiki_path: str):
        self.wiki_path = Path(wiki_path)

    async def run(self, url: str) -> dict:
        output = await _run_script(self.wiki_path, "confluence_tree.py", url)
        return {"output": output}


WIKI_SKILL_CLASSES = [
    WikiQuerySkill,
    WikiIngestSkill,
    WikiLintSkill,
    WikiReadPageSkill,
    WikiWritePageSkill,
    WikiListPagesSkill,
    WikiConfluencePageSkill,
    WikiConfluenceTreeSkill,
]

WIKI_SKILL_NAMES = [cls.__dict__["name"] for cls in WIKI_SKILL_CLASSES]
