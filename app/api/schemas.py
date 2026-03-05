from pydantic import BaseModel, Field, field_validator


class DescribeRequest(BaseModel):
    thumbnail: str = Field(description="base64 PNG or URL of lowest pyramid image")
    coordinates: list[float] = Field(
        description="[longitude, latitude]", min_length=2, max_length=2
    )

    @field_validator("thumbnail")
    @classmethod
    def validate_thumbnail_size(cls, v: str) -> str:
        max_size = 5 * 1024 * 1024
        if not v.startswith("http") and len(v) > max_size:
            raise ValueError(f"Thumbnail too large (max 5MB, got {len(v)} bytes)")
        return v

    @field_validator("coordinates")
    @classmethod
    def validate_coordinates(cls, v: list[float]) -> list[float]:
        lon, lat = v
        if not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
            raise ValueError("Invalid coordinates range")
        return v

    bbox: list[float] | None = Field(
        None, description="[west, south, east, north]", min_length=4, max_length=4
    )

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, v: list[float] | None) -> list[float] | None:
        if v is None:
            return v
        west, south, east, north = v
        if not (-180 <= west <= 180) or not (-180 <= east <= 180):
            raise ValueError("Longitude must be between -180 and 180")
        if not (-90 <= south <= 90) or not (-90 <= north <= 90):
            raise ValueError("Latitude must be between -90 and 90")
        if west >= east:
            raise ValueError("west must be less than east")
        if south >= north:
            raise ValueError("south must be less than north")
        return v

    captured_at: str | None = Field(None, description="Capture date in ISO 8601 format")
    cog_image_id: str | None = Field(None, description="Optional cog_images UUID for DB linking")
    stac_id: str | None = Field(None, description="STAC item ID for satellite mission metadata")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "thumbnail": "https://example.com/satellite-image.jpg",
                    "coordinates": [126.978, 37.566],
                    "bbox": [126.9, 37.5, 127.1, 37.6],
                    "captured_at": "2025-01-15",
                    "cog_image_id": "550e8400-e29b-41d4-a716-446655440000",
                }
            ]
        }
    }


class Location(BaseModel):
    country: str
    country_code: str
    region: str
    city: str | None = None
    place_name: str
    lat: float
    lon: float

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "country": "대한민국",
                    "country_code": "kr",
                    "region": "서울특별시",
                    "city": "서울",
                    "place_name": "서울특별시, 대한민국",
                    "lat": 37.566,
                    "lon": 126.978,
                }
            ]
        }
    }


class LandCoverClass(BaseModel):
    type: str
    label: str
    percentage: float | None = None


class LandCover(BaseModel):
    classes: list[LandCoverClass]
    summary: str

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "classes": [
                        {"type": "residential", "label": "주거지역", "percentage": 45},
                        {"type": "commercial", "label": "상업지역", "percentage": 30},
                        {"type": "park", "label": "공원", "percentage": 25},
                    ],
                    "summary": "주거지역 45%, 상업지역 30%, 공원 25%",
                }
            ]
        }
    }


class Event(BaseModel):
    title: str
    date: str
    source_url: str
    relevance: str = "medium"


class Context(BaseModel):
    events: list[Event]
    summary: str


class Mission(BaseModel):
    platform: str
    instrument: str
    constellation: str | None = None
    processing_level: str | None = None
    cloud_cover: float | None = None
    gsd: float | None = None
    spectral_bands: int | None = None


class Warning(BaseModel):
    module: str
    error: str


class DescribeResponse(BaseModel):
    description: str | None = None
    location: Location | None = None
    land_cover: LandCover | None = None
    context: Context | None = None
    mission: Mission | None = None
    warnings: list[Warning] = []
    cached: bool = False
    saved: bool | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "description": "서울 도심부의 위성영상으로, 한강이 동서로 흐르며 ...",
                    "location": {
                        "country": "대한민국",
                        "country_code": "kr",
                        "region": "서울특별시",
                        "city": "서울",
                        "place_name": "서울특별시, 대한민국",
                        "lat": 37.566,
                        "lon": 126.978,
                    },
                    "land_cover": {
                        "classes": [
                            {"type": "residential", "label": "주거지역", "percentage": 45},
                        ],
                        "summary": "주거지역 45%",
                    },
                    "context": {"events": [], "summary": "관련 정보를 찾지 못했습니다."},
                    "warnings": [],
                    "cached": False,
                }
            ]
        }
    }


MAX_BATCH_SIZE = 10


class BatchDescribeItem(BaseModel):
    """Batch item — thumbnail size validation deferred to per-item processing."""

    thumbnail: str = Field(description="base64 PNG or URL of lowest pyramid image")
    coordinates: list[float] = Field(
        description="[longitude, latitude]", min_length=2, max_length=2
    )
    bbox: list[float] | None = Field(
        None, description="[west, south, east, north]", min_length=4, max_length=4
    )
    captured_at: str | None = Field(None, description="Capture date in ISO 8601 format")
    cog_image_id: str | None = Field(None, description="Optional cog_images UUID for DB linking")
    stac_id: str | None = Field(None, description="STAC item ID for satellite mission metadata")


class BatchDescribeRequest(BaseModel):
    items: list[BatchDescribeItem] = Field(
        description="배치 분석 요청 목록 (최대 10건)",
        min_length=1,
        max_length=MAX_BATCH_SIZE,
    )


class BatchItemResult(BaseModel):
    index: int
    result: DescribeResponse | None = None
    error: str | None = None


class BatchDescribeResponse(BaseModel):
    results: list[BatchItemResult]
    total: int
    succeeded: int
    failed: int


class ErrorResponse(BaseModel):
    """API 에러 응답 모델"""

    code: str = Field(description="에러 코드")
    message: str = Field(description="에러 메시지")
    details: dict | None = Field(None, description="추가 에러 상세 정보")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "code": "NOT_FOUND",
                    "message": "Description not found for cog_image_id: ...",
                    "details": None,
                }
            ]
        }
    }
