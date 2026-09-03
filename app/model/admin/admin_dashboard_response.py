from pydantic import BaseModel


class AdminDashboardData(BaseModel):

    totalUsers: int

    totalCoBrothers: int

    totalVentureViews: int

    totalProfileViews: int

    totalVentures: int

    totalDomains: int

    totalTechnologies: int

    totalCreators: int


class AdminDashboardResponse(BaseModel):

    success: bool

    data: AdminDashboardData