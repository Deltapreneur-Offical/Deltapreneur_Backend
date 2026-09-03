from pydantic import BaseModel


class ProfileAnalyticsData(BaseModel):

    totalViews: int

    viewsThisWeek: int

    viewsByDay: dict[str, int]

    byIndustry: dict[str, int]

    byRole: dict[str, int]


class ProfileAnalyticsResponse(BaseModel):

    success: bool

    message: str | None = None

    data: ProfileAnalyticsData | None = None