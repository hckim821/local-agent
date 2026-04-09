import logging
from pathlib import Path
from .skill_base import SkillBase


class AnalyzeCSVSkill(SkillBase):
    name = "analyze_csv"
    description = (
        "CSV 파일 경로를 받아 pandas로 읽은 뒤 데이터 구조, 통계, 결측값 등을 분석합니다. "
        "사용자가 CSV 파일 분석을 요청하거나 파일 경로를 언급할 때 호출합니다."
    )
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "분석할 CSV 파일의 절대 또는 상대 경로",
            },
            "encoding": {
                "type": "string",
                "description": "파일 인코딩 (기본값: utf-8-sig, 한글 파일은 cp949 시도)",
            },
            "max_rows": {
                "type": "integer",
                "description": "미리보기로 반환할 최대 행 수 (기본값: 5)",
            },
        },
        "required": ["file_path"],
    }

    async def run(
        self,
        file_path: str,
        encoding: str = "utf-8-sig",
        max_rows: int = 5,
        **kwargs,
    ) -> dict:
        logging.info(f"[csv_skill] analyze_csv: {file_path!r} encoding={encoding}")

        try:
            import pandas as pd
        except ImportError:
            return {
                "status": "error",
                "message": "pandas가 설치되지 않았습니다. `pip install pandas`를 실행하세요.",
            }

        path = Path(file_path)
        if not path.exists():
            return {
                "status": "error",
                "message": f"파일을 찾을 수 없습니다: {file_path}",
            }
        if path.suffix.lower() not in (".csv", ".tsv", ".txt"):
            return {
                "status": "error",
                "message": f"CSV 파일이 아닙니다 (확장자: {path.suffix})",
            }

        # ── 인코딩 자동 감지 (utf-8-sig 실패 시 cp949 재시도) ──────────
        df = None
        used_encoding = encoding
        for enc in [encoding, "cp949", "utf-8", "latin-1"]:
            try:
                sep = "\t" if path.suffix.lower() == ".tsv" else ","
                df = pd.read_csv(path, encoding=enc, sep=sep)
                used_encoding = enc
                break
            except (UnicodeDecodeError, Exception):
                continue

        if df is None:
            return {
                "status": "error",
                "message": "파일을 읽을 수 없습니다. 인코딩을 확인하세요 (utf-8, cp949 등).",
            }

        logging.info(f"[csv_skill] Loaded {df.shape} with encoding={used_encoding}")

        # ── 기본 정보 ────────────────────────────────────────────────────
        rows, cols = df.shape

        # ── 컬럼 타입 ────────────────────────────────────────────────────
        col_types = {col: str(dtype) for col, dtype in df.dtypes.items()}

        # ── 결측값 ───────────────────────────────────────────────────────
        null_counts = df.isnull().sum()
        null_info = {
            col: int(cnt)
            for col, cnt in null_counts.items()
            if cnt > 0
        }

        # ── 수치형 통계 ──────────────────────────────────────────────────
        numeric_cols = df.select_dtypes(include="number").columns.tolist()
        stats: dict = {}
        if numeric_cols:
            desc = df[numeric_cols].describe().round(4)
            for col in numeric_cols:
                stats[col] = {
                    stat: float(desc.loc[stat, col])
                    for stat in desc.index
                }

        # ── 범주형 요약 ──────────────────────────────────────────────────
        categorical_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()
        cat_summary: dict = {}
        for col in categorical_cols[:5]:  # 최대 5개 컬럼
            vc = df[col].value_counts()
            cat_summary[col] = {
                "unique": int(df[col].nunique()),
                "top_values": {str(k): int(v) for k, v in vc.head(5).items()},
            }

        # ── 미리보기 ─────────────────────────────────────────────────────
        preview_rows = df.head(max_rows).fillna("").astype(str).to_dict(orient="records")

        # ── 중복 행 ──────────────────────────────────────────────────────
        duplicate_count = int(df.duplicated().sum())

        return {
            "status": "success",
            "file": str(path.resolve()),
            "encoding": used_encoding,
            "shape": {"rows": rows, "columns": cols},
            "columns": col_types,
            "null_values": null_info,
            "duplicate_rows": duplicate_count,
            "numeric_stats": stats,
            "categorical_summary": cat_summary,
            "preview": preview_rows,
            "message": (
                f"CSV 분석 완료: {rows}행 × {cols}열, "
                f"결측값 컬럼 {len(null_info)}개, "
                f"중복 행 {duplicate_count}개"
            ),
        }
