from pydantic import BaseModel


class VentureAnalyticsData(BaseModel):

    ventureId: str

    ventureName: str | None

    totalViews: int

    totalApplications: int

    conversionRate: float

    avgHoursToApply: float

    viewsByDay: dict[str, int]

    byIndustry: dict[str, int]

    byRole: dict[str, int]

    applicantSkills: dict[str, int]

    byStatus: dict[str, int]


class VentureAnalyticsResponse(BaseModel):

    success: bool

    message: str | None = None

    data: VentureAnalyticsData | None = None