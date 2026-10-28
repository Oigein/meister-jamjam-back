"""검증 가능한 난수. 같은 시드면 누구나 같은 결과를 얻는다. (알고리즘 v1)

- 난수 스트림: SHA-256(seed(UTF-8) || counter(8바이트 big-endian)), counter는 0부터 1씩 증가
- 정수: 스트림에서 8바이트씩 읽어 큰 수로 해석하고, 편향이 생기지 않도록 범위 밖 값은 버린다(rejection sampling)
- 셔플: i = n-1 → 1 까지 j = randbelow(i+1) 을 뽑아 items[i]와 items[j]를 교환 (Fisher-Yates)

파이썬 `random`은 쓰지 않는다. 시드는 `secrets`로 만든다.
"""
import hashlib
import secrets

ALGORITHM = "SHA-256 카운터 모드 PRNG + Fisher-Yates 셔플, v1"
_SPACE = 1 << 64


def generate_seed() -> str:
    return secrets.token_hex(32)


class SeededRandom:
    def __init__(self, seed: str) -> None:
        self._seed = seed.encode()
        self._counter = 0
        self._buffer = b""

    def _take(self, n: int) -> bytes:
        while len(self._buffer) < n:
            self._buffer += hashlib.sha256(self._seed + self._counter.to_bytes(8, "big")).digest()
            self._counter += 1
        out, self._buffer = self._buffer[:n], self._buffer[n:]
        return out

    def randbelow(self, n: int) -> int:
        if n <= 0:
            raise ValueError("n은 1 이상이어야 합니다.")
        limit = _SPACE - (_SPACE % n)
        while True:
            value = int.from_bytes(self._take(8), "big")
            if value < limit:
                return value % n

    def shuffle(self, items: list) -> list:
        """원본을 바꾸지 않고 섞은 새 리스트를 돌려준다."""
        out = list(items)
        for i in range(len(out) - 1, 0, -1):
            j = self.randbelow(i + 1)
            out[i], out[j] = out[j], out[i]
        return out
