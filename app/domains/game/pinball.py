"""핀볼 추첨 순수 로직. 연출(DROP/BUMPER)은 클라이언트가 서버 결과에 맞춰 재생만 한다."""
from app.domains.game.rng import SeededRandom


def draw_winners(seed: str, candidates: list[int], count: int) -> list[int]:
    """후보(번호 오름차순)를 시드로 섞어 앞에서 count명을 당첨자로 정한다 (뽑힌 순서 유지)."""
    if not 1 <= count <= len(candidates):
        raise ValueError("당첨 인원이 후보 수를 벗어났습니다.")
    return SeededRandom(seed).shuffle(sorted(candidates))[:count]
