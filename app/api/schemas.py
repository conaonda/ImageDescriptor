from pydantic import BaseModel, Field, field_validator


class DescribeRequest(BaseModel):
    thumbnail: str = Field(description="base64 PNG or URL of lowest pyramid image")
    coordinates: list[float] = Field(
        description="[longitude, latitude]", min_length=2, max_length=2
    )

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
    captured_at: str | None = Field(None, description="Capture date in ISO 8601 format")
    cog_image_id: str | None = Field(None, description="Optional cog_images UUID for DB linking")


class Location(BaseModel):
    country: str
    country_code: str
    region: str
    city: str | None = None
    place_name: str
    lat: float
    lon: float


class LandCoverClass(BaseModel):
    type: str
    label: str
    percentage: float | None = None


class LandCover(BaseModel):
    classes: list[LandCoverClass]
    summary: str


class Event(BaseModel):
    title: str
    date: str
    source_url: str
    relevance: str = "medium"


class Context(BaseModel):
    events: list[Event]
    summary: str


class Warning(BaseModel):
    module: str
    error: str


class DescribeResponse(BaseModel):
    description: str | None = None
    location: Location | None = None
    land_cover: LandCover | None = None
    context: Context | None = None
    warnings: list[Warning] = []
    cached: bool = False
