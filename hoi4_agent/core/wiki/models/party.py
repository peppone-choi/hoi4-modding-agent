"""정당 데이터 모델."""
from pydantic import BaseModel, Field


class PartyModel(BaseModel):
    """HOI4 정당/이념 데이터 모델."""

    ideology: str                         # HOI4 주요 이념 그룹 코드
    party_name: str = ""                  # 실제 정당명
    country_tag: str = ""
    is_ruling: bool = False
    popularity: int = Field(default=0, ge=0, le=100)
    leader_char_id: str = ""
    wikidata_qid: str = ""

    party_name_local: str = ""
    party_abbreviation: str = ""
    sub_ideology: str = ""
    mapping_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    mapping_source: str = ""
    needs_review: bool = False
    wikidata_party_qid: str = ""
    alternative_ideologies: list[str] = Field(default_factory=list)


if __name__ == "__main__":
    # 예시: 유효한 정당 생성
    party1 = PartyModel(
        ideology="communism",
        party_name="Korean Workers' Party",
        country_tag="KOR",
        is_ruling=True,
        popularity=60,
        leader_char_id="KOR_Kim_Il_sung_char",
        wikidata_qid="Q1234567",
    )
    print("✓ 정당 생성 성공:")
    print(f"  이념: {party1.ideology}")
    print(f"  정당명: {party1.party_name}")
    print(f"  국가: {party1.country_tag}")
    print(f"  지지율: {party1.popularity}%")
    print(f"  지배 정당: {party1.is_ruling}")
    
    # 예시: 다른 정당
    party2 = PartyModel(
        ideology="democracy",
        party_name="Democratic Party",
        country_tag="USA",
        is_ruling=True,
        popularity=45,
        leader_char_id="USA_Joe_Biden_char",
    )
    print("\n✓ 다른 정당 생성:")
    print(f"  이념: {party2.ideology}")
    print(f"  정당명: {party2.party_name}")
    print(f"  지지율: {party2.popularity}%")
