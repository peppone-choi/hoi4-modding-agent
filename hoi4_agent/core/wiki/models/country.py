"""국가 데이터 모델."""
from pydantic import BaseModel, Field, field_validator


class CountryModel(BaseModel):
    """HOI4 국가 정치 데이터 모델."""
    
    country_tag: str = Field(..., min_length=2, max_length=5)
    country_name: str = ""
    
    # 정치 (2026년 기준)
    ruling_ideology: str = ""
    elections_allowed: bool = True
    
    # 이념 지지율 (합계 100%)
    ideology_popularities: dict[str, int] = Field(default_factory=dict)
    
    # 지도자
    head_of_state_id: str = ""
    head_of_government_id: str = ""
    
    # 메타
    wikidata_qid: str = ""
    last_updated: str = ""
    
    @field_validator('ideology_popularities')
    @classmethod
    def validate_popularities_range(cls, v: dict[str, int]) -> dict[str, int]:
        """각 이념 지지율이 0-100 범위인지 확인."""
        for ideology, popularity in v.items():
            if not (0 <= popularity <= 100):
                raise ValueError(
                    f"이념 '{ideology}'의 지지율 {popularity}는 0-100 범위여야 함"
                )
        return v
    
    def validate_popularities(self) -> bool:
        """이념 지지율 합계가 100인지 확인."""
        if not self.ideology_popularities:
            return True
        total = sum(self.ideology_popularities.values())
        return total == 100
    
    def normalize_popularities(self) -> None:
        """지지율 합계를 100으로 정규화."""
        if not self.ideology_popularities:
            return
        
        total = sum(self.ideology_popularities.values())
        if total == 0:
            return
        
        # 비율 계산 및 정규화
        normalized = {}
        remainder = 100
        
        for ideology, popularity in sorted(self.ideology_popularities.items()):
            normalized_value = round((popularity / total) * 100)
            normalized[ideology] = normalized_value
            remainder -= normalized_value
        
        # 반올림 오차 보정 (가장 큰 값에 추가)
        if remainder != 0:
            max_ideology = max(normalized, key=normalized.get)
            normalized[max_ideology] += remainder
        
        self.ideology_popularities = normalized


if __name__ == "__main__":
    # 예시: 유효한 국가 생성
    country = CountryModel(
        country_tag="KOR",
        country_name="Korea",
        ruling_ideology="communism",
        elections_allowed=False,
        ideology_popularities={
            "communism": 60,
            "fascism": 20,
            "democracy": 20,
        },
        head_of_state_id="KOR_Kim_Il_sung_char",
        head_of_government_id="KOR_Kim_Il_sung_char",
    )
    print("✓ 국가 생성 성공:")
    print(f"  태그: {country.country_tag}")
    print(f"  이름: {country.country_name}")
    print(f"  지배 이념: {country.ruling_ideology}")
    print(f"  이념 지지율 합계 유효: {country.validate_popularities()}")
    print(f"  이념 지지율: {country.ideology_popularities}")
    
    # 예시: 정규화
    country2 = CountryModel(
        country_tag="USA",
        country_name="United States",
        ruling_ideology="democracy",
        ideology_popularities={
            "democracy": 50,
            "fascism": 30,
            "communism": 15,
        },
    )
    print("\n✓ 정규화 전:")
    print(f"  합계: {sum(country2.ideology_popularities.values())}")
    country2.normalize_popularities()
    print("✓ 정규화 후:")
    print(f"  합계: {sum(country2.ideology_popularities.values())}")
    print(f"  지지율: {country2.ideology_popularities}")
