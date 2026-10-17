"""추적 가능한 집계만 읽는다. 인메모리 프리로딩·DuckDB/Parquet 어댑터·복기 동기화 저장소를 제공한다."""

from __future__ import annotations

import csv
import json
import logging
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
REPO = 'https://github.com/jinwon25/lol-live-ops-analytics/blob/main/'
DEFAULT_SERVICE_DB_PATH = ROOT / 'data' / 'processed' / 'lol_service.db'
DEFAULT_HISTORIC_DB_PATH = ROOT / 'data' / 'processed' / 'lol.db'
MINIMUM_ELIGIBLE_PICKS = 30
MAX_SYNCED_REVIEWS = 500

SCOPE = {
    'patches': ['15.1', '15.3'],
    'region': 'EUN',
    'queue': '솔로듀오',
    'cohort': 'PLATINUM·EMERALD·DIAMOND',
    'unit': '경기×참여자',
    'is_current_match_data': False,
}


@lru_cache(maxsize=32)
def _cached_rows(filename: str) -> tuple[dict[str, str], ...]:
    """Load and cache CSV rows in memory once to avoid repeated disk I/O."""
    csv_path = ROOT / 'outputs' / filename
    with csv_path.open(encoding='utf-8-sig', newline='') as stream:
        return tuple(csv.DictReader(stream))


def rows(filename: str) -> list[dict[str, str]]:
    """Return preloaded CSV rows from memory cache."""
    return [dict(row) for row in _cached_rows(filename)]


@lru_cache(maxsize=1)
def catalogue() -> dict[str, Any]:
    return json.loads((ROOT / 'service/data/catalogue.json').read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def catalogue_by_id() -> dict[str, dict[str, Any]]:
    """Return an O(1) lookup dictionary mapping champion ID to static metadata."""
    return {champ['id']: champ for champ in catalogue()['champions']}


@lru_cache(maxsize=1)
def _champion_history_index() -> dict[str, tuple[dict[str, str], ...]]:
    """Build an O(1) case-folded lookup table for champion historic stats."""
    indexed: dict[str, list[dict[str, str]]] = {}
    for row in _cached_rows('champion_meta.csv'):
        key = row.get('champion_en', '').casefold()
        if key:
            indexed.setdefault(key, []).append(row)
    return {key: tuple(items) for key, items in indexed.items()}


def champion_history(champion_id: str) -> list[dict[str, str]]:
    """Return historic cohort rows for champion_id in O(1) time via in-memory index."""
    if not champion_id:
        return []
    matched = _champion_history_index().get(champion_id.casefold(), ())
    return [dict(row) for row in matched]


def preload_evidence() -> None:
    """Preload static catalogue and core CSV datasets into memory on startup."""
    catalogue()
    catalogue_by_id()
    _cached_rows('diversity.csv')
    _cached_rows('segment_summary.csv')
    _cached_rows('champion_meta.csv')
    _champion_history_index()


class DuckDBAdapter:
    """Analytical query adapter supporting DuckDB + Parquet with automatic SQLite/CSV fallback."""

    def __init__(self, parquet_dir: Path | None = None, sqlite_path: Path | None = None):
        self.parquet_dir = parquet_dir or (ROOT / 'data' / 'processed')
        self.sqlite_path = sqlite_path or DEFAULT_HISTORIC_DB_PATH

    @staticmethod
    def is_duckdb_available() -> bool:
        try:
            import duckdb  # noqa: F401

            return True
        except ImportError:
            return False

    def query_parquet(
        self, parquet_path: Path | str, sql_query: str, params: list[Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute an analytical SQL query against a Parquet file using DuckDB (or fallback)."""
        resolved_path = Path(parquet_path)
        if self.is_duckdb_available() and resolved_path.exists():
            import duckdb

            with duckdb.connect(database=':memory:') as connection:
                formatted_sql = sql_query.replace('{parquet}', f"read_parquet('{resolved_path.as_posix()}')")
                cursor = connection.execute(formatted_sql, params or [])
                columns = [col[0] for col in cursor.description]
                return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]

        if self.sqlite_path.exists():
            with closing(sqlite3.connect(self.sqlite_path)) as connection:
                connection.row_factory = sqlite3.Row
                fallback_sql = sql_query.replace('{parquet}', 'participants')
                sqlite_cursor = connection.execute(fallback_sql, params or [])
                return [dict(row) for row in sqlite_cursor.fetchall()]
        return []

    def query_champion_history(self, champion_id: str) -> list[dict[str, Any]]:
        """Query champion meta history via DuckDB Parquet if exported, falling back to in-memory index."""
        parquet_file = self.parquet_dir / 'champion_meta.parquet'
        if self.is_duckdb_available() and parquet_file.exists():
            return self.query_parquet(
                parquet_file,
                'SELECT * FROM {parquet} WHERE LOWER(champion_en) = LOWER(?)',
                [champion_id],
            )
        return champion_history(champion_id)

    def export_csv_to_parquet(self, csv_filename: str, parquet_filename: str | None = None) -> Path | None:
        """Convert an outputs CSV file into Parquet format when DuckDB is installed."""
        if not self.is_duckdb_available():
            return None
        import duckdb

        source_csv = ROOT / 'outputs' / csv_filename
        target_name = parquet_filename or (Path(csv_filename).stem + '.parquet')
        target_parquet = self.parquet_dir / target_name
        target_parquet.parent.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(database=':memory:') as connection:
            connection.execute(
                f"COPY (SELECT * FROM read_csv_auto('{source_csv.as_posix()}')) "
                f"TO '{target_parquet.as_posix()}' (FORMAT PARQUET)"
            )
        return target_parquet


REVIEW_SYNC_SCHEMA = """
CREATE TABLE IF NOT EXISTS synced_reviews (
    record_id   TEXT PRIMARY KEY,
    client_id   TEXT NOT NULL,
    context_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    focus       TEXT NOT NULL,
    scene       TEXT NOT NULL,
    action      TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'planned',
    reflection  TEXT NOT NULL DEFAULT '',
    played_at   TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_synced_reviews_client ON synced_reviews(client_id, played_at DESC);

CREATE TABLE IF NOT EXISTS meta_snapshots (
    snapshot_id  TEXT PRIMARY KEY,
    collected_at TEXT NOT NULL,
    patch        TEXT NOT NULL,
    region       TEXT NOT NULL,
    games        INTEGER NOT NULL,
    participants INTEGER NOT NULL,
    scope_json   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta_champion_stats (
    snapshot_id  TEXT NOT NULL,
    patch        TEXT NOT NULL,
    champion_id  TEXT NOT NULL,
    role         TEXT NOT NULL,
    games        INTEGER NOT NULL,
    wins         INTEGER NOT NULL,
    win_rate     REAL,
    pick_rate    REAL NOT NULL,
    ban_rate     REAL,
    signal       TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, champion_id, role)
);
"""


class ReviewSyncStore:
    """Persistent backend store for user review notes and unified stratified meta aggregates."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or DEFAULT_SERVICE_DB_PATH
        self._initialized = False

    def _ensure_schema(self) -> None:
        if self._initialized and self.db_path.exists():
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.executescript(REVIEW_SYNC_SCHEMA)
            connection.commit()
        self._initialized = True

    @staticmethod
    def _serialize_row(row: sqlite3.Row) -> dict[str, Any]:
        context = json.loads(row['context_json'])
        record = {
            'id': row['record_id'],
            'record_id': row['record_id'],
            'client_id': row['client_id'],
            'context': context,
            'metrics': json.loads(row['metrics_json']),
            'focus': row['focus'],
            'scene': row['scene'],
            'action': row['action'],
            'status': row['status'],
            'reflection': row['reflection'],
            'note': row['reflection'] or context.get('note', ''),
            'played_at': row['played_at'],
            'updated_at': row['updated_at'],
        }
        for key in ('champion_id', 'role', 'patch', 'tags'):
            if key in context:
                record[key] = context[key]
        return record

    def list_reviews(self, client_id: str = 'default') -> list[dict[str, Any]]:
        self._ensure_schema()
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.row_factory = sqlite3.Row
            rows_cursor = connection.execute(
                """
                SELECT record_id, client_id, context_json, metrics_json, focus,
                       scene, action, status, reflection, played_at, updated_at
                FROM synced_reviews
                WHERE client_id = ?
                ORDER BY played_at DESC, updated_at DESC
                LIMIT ?
                """,
                (client_id, MAX_SYNCED_REVIEWS),
            )
            return [self._serialize_row(row) for row in rows_cursor.fetchall()]

    def get_review(self, record_id: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.execute(
                """
                SELECT record_id, client_id, context_json, metrics_json, focus,
                       scene, action, status, reflection, played_at, updated_at
                FROM synced_reviews
                WHERE record_id = ?
                """,
                (record_id,),
            )
            row = cursor.fetchone()
            return self._serialize_row(row) if row is not None else None

    def upsert_review(self, payload: dict[str, Any], record_id: str | None = None) -> dict[str, Any]:
        self._ensure_schema()
        resolved_id = record_id or payload.get('record_id') or uuid.uuid4().hex
        client_id = str(payload.get('client_id') or 'default').strip() or 'default'
        context = dict(payload.get('context') or {})
        for field_name in ('champion_id', 'role', 'patch', 'tags', 'note'):
            if payload.get(field_name) is not None and field_name not in context:
                context[field_name] = payload[field_name]
        metrics = payload.get('metrics') or {}
        played_at = str(context.get('played_at') or payload.get('played_at') or datetime.now(UTC).isoformat())
        updated_at = datetime.now(UTC).isoformat()
        focus = str(payload.get('focus') or 'vision')
        scene = str(payload.get('scene') or '').strip()
        action = str(payload.get('action') or '').strip()
        status = str(payload.get('status') or 'planned')
        reflection = str(payload.get('reflection') or payload.get('note') or '').strip()

        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                """
                INSERT INTO synced_reviews (
                    record_id, client_id, context_json, metrics_json, focus,
                    scene, action, status, reflection, played_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(record_id) DO UPDATE SET
                    context_json = excluded.context_json,
                    metrics_json = excluded.metrics_json,
                    focus = excluded.focus,
                    scene = excluded.scene,
                    action = excluded.action,
                    status = excluded.status,
                    reflection = excluded.reflection,
                    played_at = excluded.played_at,
                    updated_at = excluded.updated_at
                """,
                (
                    resolved_id,
                    client_id,
                    json.dumps(context, ensure_ascii=False),
                    json.dumps(metrics, ensure_ascii=False),
                    focus,
                    scene,
                    action,
                    status,
                    reflection,
                    played_at,
                    updated_at,
                ),
            )
            connection.commit()

        result = {
            'id': resolved_id,
            'record_id': resolved_id,
            'client_id': client_id,
            'context': context,
            'metrics': metrics,
            'focus': focus,
            'scene': scene,
            'action': action,
            'status': status,
            'reflection': reflection,
            'note': reflection,
            'played_at': played_at,
            'updated_at': updated_at,
        }
        for key in ('champion_id', 'role', 'patch', 'tags'):
            if key in context:
                result[key] = context[key]
        return result

    def delete_review(self, record_id: str, client_id: str = 'default') -> bool:
        self._ensure_schema()
        with closing(sqlite3.connect(self.db_path)) as connection:
            cursor = connection.execute(
                'DELETE FROM synced_reviews WHERE record_id = ? AND client_id = ?',
                (record_id, client_id),
            )
            connection.commit()
            return cursor.rowcount > 0

    def persist_meta_snapshot(self, report: dict[str, Any]) -> str:
        """Store aggregated current-patch meta statistics into unified relational tables."""
        self._ensure_schema()
        snapshot_id = uuid.uuid4().hex
        scope = report.get('scope') or {}
        patch = str(scope.get('patch') or '')
        region = str(scope.get('region') or 'KR')
        collected_at = str(report.get('collected_at') or report.get('generated_at') or datetime.now(UTC).isoformat())
        games = int(report.get('games') or 0)
        participants = int(report.get('participants') or 0)

        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.execute(
                """
                INSERT INTO meta_snapshots (
                    snapshot_id, collected_at, patch, region, games, participants, scope_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    collected_at,
                    patch,
                    region,
                    games,
                    participants,
                    json.dumps(scope, ensure_ascii=False),
                ),
            )
            stat_rows = [
                (
                    snapshot_id,
                    patch,
                    item['champion_id'],
                    item['role'],
                    int(item['games']),
                    int(item['wins']),
                    item.get('win_rate'),
                    float(item['pick_rate']),
                    item.get('ban_rate'),
                    str(item['signal']),
                )
                for item in report.get('items', [])
            ]
            if stat_rows:
                connection.executemany(
                    """
                    INSERT INTO meta_champion_stats (
                        snapshot_id, patch, champion_id, role, games, wins,
                        win_rate, pick_rate, ban_rate, signal
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    stat_rows,
                )
            connection.commit()
        return snapshot_id

    def latest_meta_snapshot(self) -> dict[str, Any] | None:
        """Return the most recently persisted meta snapshot summary."""
        self._ensure_schema()
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.execute(
                """
                SELECT snapshot_id, collected_at, patch, region, games, participants, scope_json
                FROM meta_snapshots
                ORDER BY collected_at DESC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return {
                'snapshot_id': row['snapshot_id'],
                'collected_at': row['collected_at'],
                'patch': row['patch'],
                'region': row['region'],
                'games': row['games'],
                'participants': row['participants'],
                'scope': json.loads(row['scope_json']),
            }


duckdb_adapter = DuckDBAdapter()
review_store = ReviewSyncStore()


def answer(question, champion_id=None):
    query_lower = question.casefold()
    sources_list: list[dict[str, Any]] = []
    caveats_list: list[str] = ['기존 경기 표본은 2025년 초 패치 15.1·15.3이며 현재 메타를 대표하지 않습니다.']
    result: dict[str, Any] = {
        'status': 'documented',
        'scope': SCOPE,
        'sources': sources_list,
        'caveats': caveats_list,
        'next_step': '근거와 비교 조건을 확인한 뒤 검토할 질문 한 가지를 복기 노트에 남겨보세요.',
    }
    if any(word in query_lower for word in ['내 전적', '내 최근', '내 승률', '내 실력', '팀운', '내 티어']):
        result.update(
            status='insufficient_data',
            answer='경기 복기 화면에서 공식 KR 솔로듀오 전적을 불러오거나 수치를 직접 입력할 수 있습니다. 복기 보드에 저장한 경기에서 같은 지역·랭크 큐·패치·티어·챔피언·역할의 내 기록을 비교할 수 있습니다. 이 도우미에는 브라우저의 개인 기록이 전달되지 않아 내 실력이나 팀운을 판정할 수 없습니다.',
            scope={
                'patches': [],
                'region': '사용자 선택',
                'cohort': '내 직접 입력 경기',
                'unit': '완료 경기',
                'is_current_match_data': False,
            },
            sources=[{'title': '개인 복기와 비교 조건', 'url': REPO + 'docs/06_companion_plan.md'}],
            caveats=[
                '직접 입력은 전적 API로 확인되지 않은 기록입니다. 내 기록의 전후 차이는 인과효과나 실력 점수가 아닙니다.'
            ],
        )
    elif any(
        word in query_lower for word in ['최신', '지금', '현재', '추천', '사기', '티어리스트', '아이템', '룬', '빌드']
    ):
        cat = catalogue()
        result.update(
            status='insufficient_data',
            answer=f'확인된 공식 챔피언 정적 자료는 {cat["version"]}입니다. 챔피언 이름·분류·기본 수치를 확인할 수 있지만 최신 승률·추천 빌드를 계산할 경기 표본은 연결되지 않았습니다. 과거 승률을 현재 추천으로 바꾸어 답하지 않습니다.',
            sources=[
                {'title': '공식 Data Dragon 정적 자료', 'url': cat['source_url']},
                {'title': 'Riot API와 정적 자료의 구분', 'url': 'https://developer.riotgames.com/docs/lol'},
            ],
        )
        champ = next((item for item in cat['champions'] if item['id'] == champion_id), None)
        result['external_references'] = [
            {
                'title': 'LOL.PS 챔피언 통계·매치업',
                'url': f'https://lol.ps/champ/{champ["key"]}' if champ else 'https://lol.ps/',
            },
            {'title': 'FOW 전적·챔피언 정보', 'url': 'https://www.fow.lol/'},
        ]
        result['next_step'] = (
            '외부 통계에서 패치·티어·역할·표본 수를 확인하고, 내 경기에서 검토할 질문으로 가져오세요. 외부 자료는 이 서비스에 자동 수집되지 않습니다.'
        )
        from service.meta import current_meta

        meta_data = current_meta()
        if (
            meta_data.get('available')
            and not meta_data.get('stale')
            and not any(word in query_lower for word in ['아이템', '룬', '빌드'])
        ):
            observed = [
                row
                for row in meta_data['items']
                if row['win_rate'] is not None and (not champion_id or row['champion_id'] == champion_id)
            ]
            observed.sort(key=lambda row: row['interval'][0], reverse=True)
            names = {item['id']: item['name'] for item in cat['champions']}
            detail = ' / '.join(
                f'{names.get(row["champion_id"], row["champion_id"])} {row["role"]}: {row["games"]}회, 관측 승률 {row["win_rate"]}%, 참고 구간 {row["interval"][0]}–{row["interval"][1]}%'
                for row in observed[:3]
            )
            result.update(
                status='documented' if observed else 'insufficient_data',
                answer=f'현재 연결한 {meta_data["scope"]["patch"]} KR 솔로듀오 {meta_data["games"]}경기의 제한 표본입니다. '
                + (
                    detail + '. 승률 구간 하한 순의 관측 요약이며 확정적인 챔피언 티어는 아닙니다.'
                    if observed
                    else '선택한 챔피언의 역할별 표본이 30회 미만이거나 관측되지 않아 승률 설명을 보류합니다.'
                ),
                scope={
                    **meta_data['scope'],
                    'patches': [meta_data['scope']['patch']],
                    'cohort': 'SILVER II 계정에서 출발한 제한 표본',
                    'unit': '경기×참여자',
                    'is_current_match_data': True,
                },
                sources=meta_data['sources'],
                caveats=meta_data['caveats'],
                next_step='데이터 인사이트의 현재 패치 통계에서 포지션·승률 구간·픽 비중·표본 수를 함께 확인하세요.',
            )
    elif any(word in query_lower for word in ['패치', '메타', '변화', '승률', '챔피언']):
        history = champion_history(champion_id) if champion_id else []
        if history:
            eligible = [row for row in history if int(row['pick_count']) >= MINIMUM_ELIGIBLE_PICKS]
            detail = ' / '.join(
                f'{row["patch"]} {row["role"]}: {row["pick_count"]}행, 관측 승률 {row["win_rate_pct"]}%'
                for row in eligible[:5]
            )
            result['answer'] = (
                '선택한 챔피언의 과거 코호트 집계입니다. '
                + detail
                + '. 표본 수·역할을 함께 확인하세요. 다른 챔피언·상대·숙련도 차이는 남아 있습니다.'
                if eligible
                else '선택한 챔피언은 과거 역할별 표본이 모두 30행 미만이라 승률로 강함을 판단하지 않습니다.'
            )
            if len(eligible) < len(history):
                caveats_list.append(
                    '30행 미만인 역할·패치의 승률 설명은 보류했습니다. 30행은 표시용 최소 기준이며 충분한 정밀도를 보장하지 않습니다.'
                )
        else:
            result['answer'] = (
                '기존 분석에서 이즈리얼의 픽 비중 변화는 전체 표본 +0.35%p, 공통 티어 표본 +0.13%p였습니다. 비교 조건에 민감한 신호라는 뜻이며 티어가 변화를 전부 설명하거나 패치의 인과효과를 측정했다는 뜻은 아닙니다.'
            )
            if champion_id:
                result['status'] = 'insufficient_data'
                result['answer'] = (
                    '선택한 챔피언에 대한 과거 집계가 없습니다. 현재 공식 목록에 있다는 사실만으로 승률이나 추천을 만들 수 없습니다.'
                )
        result['sources'] = [
            {'title': '챔피언별 역할·패치 집계', 'url': REPO + 'outputs/champion_meta.csv'},
            {'title': '메타 분석 설계와 해석', 'url': REPO + 'docs/02_phase2_notes.md'},
        ]
        caveats_list.append('여러 챔피언 비교의 다중검정과 경기 내 관측 의존성은 후속 검증 대상입니다.')
    elif any(word in query_lower for word in ['군집', '유형', '성향', '스타일', '페르소나']):
        result['answer'] = (
            'K=4 군집은 한 경기의 행동 유형을 요약합니다. 분당 골드·딜, 시야 점수, 킬 관여율을 역할 안에서 표준화했습니다. 같은 사람을 여러 경기에서 추적한 성격 검사가 아니며, 승패와 경기 흐름의 영향도 남아 있습니다.'
        )
        result['sources'] = [
            {'title': '행동 군집의 입력과 한계', 'url': REPO + 'docs/03_phase3_notes.md'},
            {'title': '군집 집계', 'url': REPO + 'outputs/segment_summary.csv'},
        ]
    elif any(word in query_lower for word in ['복기', '시야', '연습', '교전', '골드']):
        result['answer'] = (
            '완료된 경기에서 확인할 질문을 하나 정해보세요. 예를 들어 오브젝트 직전의 시야 확보 과정이나 교전 전 자원 차이를 기록할 수 있습니다. 집계 수치 하나로 잘못된 플레이나 실력을 판정할 수 없어, 현재 복기 화면은 수동 입력의 요약과 질문만 제공합니다.'
        )
        result['sources'] = [{'title': '복기 데이터와 검증 계획', 'url': REPO + 'docs/06_companion_plan.md'}]
        caveats_list.append('연습 과제는 검증할 가설입니다. 승률 향상 효과가 입증된 처방은 아닙니다.')
    else:
        result.update(
            status='insufficient_data',
            answer='현재 등록된 근거로는 이 질문에 답하기 어렵습니다. 패치 변화, 선택한 챔피언의 과거 집계, 행동 유형, 경기 복기 질문을 물어보세요. 최신 룬·빌드와 브라우저의 개인 기록은 이 도우미에 연결되지 않았습니다.',
        )
    return result
