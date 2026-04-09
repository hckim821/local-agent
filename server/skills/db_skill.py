import logging
from .skill_base import SkillBase

# ── DB 연결 정보 (환경에 맞게 수정하세요) ──────────────────────────
DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "your_database"
DB_USER = "your_user"
DB_PASSWORD = "your_password"
DB_TABLE = "your_table"      # Maker, IP 컬럼이 있는 테이블
DB_MAKER_COL = "Maker"       # 설비사명 컬럼
DB_IP_COL = "IP"             # VM IP 컬럼
# ──────────────────────────────────────────────────────────────────


class GetVMIPsByMakerSkill(SkillBase):
    name = "get_vm_ips_by_maker"
    description = (
        "설비사명(Maker)을 전달하면 PostgreSQL DB에서 해당 설비사의 VM IP 목록을 반환합니다. "
        "설비사 IP 조회, VM 목록 확인 요청 시 호출합니다."
    )
    parameters = {
        "type": "object",
        "properties": {
            "maker": {
                "type": "string",
                "description": "조회할 설비사명 (부분 일치 검색)",
            },
        },
        "required": ["maker"],
    }

    async def run(self, maker: str, **kwargs) -> dict:
        logging.info(f"[db_skill] get_vm_ips_by_maker: maker={maker!r}")

        try:
            import psycopg2
            import psycopg2.extras
        except ImportError:
            return {
                "status": "error",
                "message": "psycopg2가 설치되지 않았습니다. `pip install psycopg2-binary`를 실행하세요.",
            }

        conn = None
        try:
            conn = psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                connect_timeout=5,
            )
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            query = f"""
                SELECT "{DB_IP_COL}", "{DB_MAKER_COL}"
                FROM "{DB_TABLE}"
                WHERE "{DB_MAKER_COL}" ILIKE %s
                ORDER BY "{DB_IP_COL}"
            """
            cur.execute(query, (f"%{maker}%",))
            rows = cur.fetchall()
            cur.close()

            if not rows:
                return {
                    "status": "not_found",
                    "maker": maker,
                    "message": f"'{maker}'에 해당하는 설비사의 VM IP를 찾지 못했습니다.",
                    "ips": [],
                    "count": 0,
                }

            ip_list = [row[DB_IP_COL] for row in rows]
            matched_makers = list({row[DB_MAKER_COL] for row in rows})

            logging.info(f"[db_skill] Found {len(ip_list)} IPs for maker={maker!r}")

            return {
                "status": "success",
                "maker": maker,
                "matched_makers": matched_makers,
                "ips": ip_list,
                "count": len(ip_list),
                "message": f"'{maker}' 설비사 VM IP {len(ip_list)}개를 찾았습니다.",
            }

        except psycopg2.OperationalError as e:
            logging.error(f"[db_skill] DB 연결 실패: {e}")
            return {
                "status": "error",
                "message": f"DB 연결에 실패했습니다. 연결 정보를 확인하세요. ({e})",
            }
        except Exception as e:
            logging.error(f"[db_skill] 쿼리 오류: {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"쿼리 실행 중 오류가 발생했습니다: {e}",
            }
        finally:
            if conn:
                conn.close()
