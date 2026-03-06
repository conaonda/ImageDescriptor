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

    model_config = {
        "json_schema_extra": {
            "examples": [{"type": "residential", "label": "주거지역", "percentage": 45.0}]
        }
    }


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

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "title": "서울 도심 재개발 사업 착공",
                    "date": "2025-01-10",
                    "source_url": "https://example.com/news/1",
                    "relevance": "high",
                }
            ]
        }
    }


class Context(BaseModel):
    events: list[Event]
    summary: str

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "events": [
                        {
                            "title": "서울 도심 재개발 사업 착공",
                            "date": "2025-01-10",
                            "source_url": "https://example.com/news/1",
                            "relevance": "high",
                        }
                    ],
                    "summary": "촬영 시점 주변에 도심 재개발 관련 이벤트가 확인되었습니다.",
                }
            ]
        }
    }


class Mission(BaseModel):
    platform: str
    instrument: str
    constellation: str | None = None
    processing_level: str | None = None
    cloud_cover: float | None = None
    gsd: float | None = None
    spectral_bands: int | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "platform": "Sentinel-2",
                    "instrument": "MSI",
                    "constellation": "Copernicus",
                    "processing_level": "L2A",
                    "cloud_cover": 5.2,
                    "gsd": 10.0,
                    "spectral_bands": 13,
                }
            ]
        }
    }


class Warning(BaseModel):
    module: str
    error: str

    model_config = {
        "json_schema_extra": {
            "examples": [{"module": "geocoder", "error": "Nominatim timeout after 5s"}]
        }
    }


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

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "thumbnail": "https://example.com/satellite-image.jpg",
                    "coordinates": [126.978, 37.566],
                    "bbox": [126.9, 37.5, 127.1, 37.6],
                    "captured_at": "2025-01-15",
                }
            ]
        }
    }


class BatchDescribeRequest(BaseModel):
    items: list[BatchDescribeItem] = Field(
        description="배치 분석 요청 목록 (최대 10건)",
        min_length=1,
        max_length=MAX_BATCH_SIZE,
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "items": [
                        {
                            "thumbnail": "https://example.com/image1.jpg",
                            "coordinates": [126.978, 37.566],
                            "captured_at": "2025-01-15",
                        },
                        {
                            "thumbnail": "https://example.com/image2.jpg",
                            "coordinates": [129.075, 35.179],
                        },
                    ]
                }
            ]
        }
    }


class BatchItemResult(BaseModel):
    index: int
    result: DescribeResponse | None = None
    error: str | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "index": 0,
                    "result": {
                        "description": "서울 도심부의 위성영상입니다.",
                        "cached": False,
                        "warnings": [],
                    },
                    "error": None,
                }
            ]
        }
    }


class BatchDescribeResponse(BaseModel):
    results: list[BatchItemResult]
    total: int
    succeeded: int
    failed: int

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "results": [
                        {
                            "index": 0,
                            "result": {
                                "description": "서울 도심부의 위성영상입니다.",
                                "cached": False,
                                "warnings": [],
                            },
                            "error": None,
                        },
                        {"index": 1, "result": None, "error": "Timeout exceeded"},
                    ],
                    "total": 2,
                    "succeeded": 1,
                    "failed": 1,
                }
            ]
        }
    }


class CircuitBreakerStatus(BaseModel):
    name: str = Field(description="서비스 이름")
    state: str = Field(description="Circuit breaker 상태 (closed/open)")
    failure_count: int = Field(description="현재 연속 실패 횟수")
    cooldown_remaining: float = Field(description="Open 상태 시 남은 cooldown 시간(초)")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "geocoder",
                    "state": "closed",
                    "failure_count": 0,
                    "cooldown_remaining": 0.0,
                }
            ]
        }
    }


class CircuitBreakerResponse(BaseModel):
    breakers: list[CircuitBreakerStatus]

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "breakers": [
                        {
                            "name": "geocoder",
                            "state": "closed",
                            "failure_count": 0,
                            "cooldown_remaining": 0.0,
                        }
                    ]
                }
            ]
        }
    }


class ModuleStats(BaseModel):
    hits: int = Field(description="캐시 히트 횟수")
    misses: int = Field(description="캐시 미스 횟수")
    hit_rate: float = Field(description="히트율 (0.0 ~ 1.0)")

    model_config = {
        "json_schema_extra": {"examples": [{"hits": 10, "misses": 3, "hit_rate": 0.7692}]}
    }


class CacheStatsResponse(BaseModel):
    entry_count: int = Field(description="캐시 항목 수")
    total_bytes: int = Field(description="캐시 총 크기(바이트)")
    modules: dict[str, ModuleStats] = Field(description="모듈별 캐시 통계")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "entry_count": 42,
                    "total_bytes": 102400,
                    "modules": {
                        "geocode": {"hits": 10, "misses": 3, "hit_rate": 0.7692},
                    },
                }
            ]
        }
    }


class DependencyCheck(BaseModel):
    supabase: str = Field(description="Supabase 연결 상태")
    cache: str = Field(description="캐시 연결 상태")

    model_config = {"json_schema_extra": {"examples": [{"supabase": "ok", "cache": "ok"}]}}


class HealthResponse(BaseModel):
    status: str = Field(description="서비스 상태 (ok/degraded/unhealthy/shutting_down)")
    version: str = Field(description="서비스 버전")
    checks: DependencyCheck = Field(description="의존성 상태")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "status": "ok",
                    "version": "0.16.0",
                    "checks": {"supabase": "ok", "cache": "ok"},
                }
            ]
        }
    }


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
