from __future__ import annotations


class Artifact:
    
    def __init__(
        self,
        name,
        ):
        self.name = name

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Artifact):
            raise ValueError(f"Cannot compare Artifact with {type(other)}")

        return self.name == other.name

    def __str__(self) -> str:
        return self.name


if __name__ == "__main__":
    artifact = Artifact("STL")
    print(artifact)