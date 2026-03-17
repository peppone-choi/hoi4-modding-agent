"""캐릭터 데이터 모델."""
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field, field_validator
import re


class CharacterModel(BaseModel):
    """HOI4 캐릭터 완전 데이터 모델."""
    
    # 기본 식별 정보
    char_id: str = Field(..., pattern=r'^[A-Z0-9_]+_[a-zA-Z0-9_]+_char$')
    country_tag: str = Field(..., min_length=2, max_length=5)
    name_key: str                         # localisation key
    
    # 인물 정보
    name_en: str = ""
    name_ko: str = ""
    gender: str = Field(default="male", pattern=r'^(male|female|undefined)$')
    birth_date: str = ""                  # ISO: "1946-06-14"
    death_date: str = ""
    
    # HOI4 역할
    ideology: str = ""                    # 국가 지도자 이념
    leader_traits: list[str] = Field(default_factory=list)
    
    # 군사 데이터
    is_commander: bool = False
    is_field_marshal: bool = False
    is_navy_leader: bool = False
    commander_skill: int = Field(default=1, ge=1, le=5)
    commander_attack: int = Field(default=1, ge=1, le=5)
    commander_defense: int = Field(default=1, ge=1, le=5)
    commander_planning: int = Field(default=1, ge=1, le=5)
    commander_logistics: int = Field(default=1, ge=1, le=5)
    
    # 초상화
    portrait_civilian: str = ""
    portrait_army: str = ""
    
    # 메타데이터
    wikidata_qid: str = ""
    wikipedia_url: str = ""
    last_updated: str = ""               # ISO datetime
    data_sources: list[str] = Field(default_factory=list)
    
    @field_validator('birth_date', 'death_date')
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        if v and not re.match(r'^\d{4}-\d{2}-\d{2}$', v):
            raise ValueError(f"날짜 형식이 잘못됨: {v}. ISO 형식(YYYY-MM-DD) 필요")
        return v
    
    def is_alive_at(self, date: str = "2026-01-01") -> bool:
        """특정 날짜에 생존 여부."""
        if not self.birth_date:
            return False
        
        try:
            birth = datetime.strptime(self.birth_date, "%Y-%m-%d").date()
            check_date = datetime.strptime(date, "%Y-%m-%d").date()
            
            if check_date < birth:
                return False
            
            if self.death_date:
                death = datetime.strptime(self.death_date, "%Y-%m-%d").date()
                return check_date <= death
            
            return True
        except ValueError:
            return False
    
    def age_at(self, date: str = "2026-01-01") -> int | None:
        """특정 날짜의 나이."""
        if not self.birth_date:
            return None
        
        try:
            birth = datetime.strptime(self.birth_date, "%Y-%m-%d").date()
            check_date = datetime.strptime(date, "%Y-%m-%d").date()
            
            if check_date < birth:
                return None
            
            age = check_date.year - birth.year
            if (check_date.month, check_date.day) < (birth.month, birth.day):
                age -= 1
            
            return age
        except ValueError:
            return None
    
    def to_hoi4_dict(self) -> dict:
        """HOI4 generator에 전달할 딕셔너리로 변환."""
        return {
            "char_id": self.char_id,
            "country_tag": self.country_tag,
            "name_key": self.name_key,
            "name_en": self.name_en,
            "name_ko": self.name_ko,
            "gender": self.gender,
            "birth_date": self.birth_date,
            "death_date": self.death_date,
            "ideology": self.ideology,
            "leader_traits": self.leader_traits,
            "is_commander": self.is_commander,
            "is_field_marshal": self.is_field_marshal,
            "is_navy_leader": self.is_navy_leader,
            "commander_skill": self.commander_skill,
            "commander_attack": self.commander_attack,
            "commander_defense": self.commander_defense,
            "commander_planning": self.commander_planning,
            "commander_logistics": self.commander_logistics,
            "portrait_civilian": self.portrait_civilian,
            "portrait_army": self.portrait_army,
        }


if __name__ == "__main__":
    # 예시: 유효한 캐릭터 생성
    char = CharacterModel(
        char_id="KOR_Kim_Il_sung_char",
        country_tag="KOR",
        name_key="KOR_Kim_Il_sung",
        name_en="Kim Il-sung",
        name_ko="김일성",
        gender="male",
        birth_date="1912-04-15",
        death_date="1994-07-08",
        ideology="communism",
        leader_traits=["revolutionary", "popular_figurehead"],
        is_commander=True,
        commander_skill=3,
    )
    print("✓ 캐릭터 생성 성공:")
    print(f"  ID: {char.char_id}")
    print(f"  이름: {char.name_en} ({char.name_ko})")
    print(f"  생존 여부 (2026-01-01): {char.is_alive_at()}")
    print(f"  나이 (2026-01-01): {char.age_at()}")
    print(f"\n✓ HOI4 딕셔너리 변환:")
    print(f"  {char.to_hoi4_dict()}")
