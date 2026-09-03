from fastapi import APIRouter, UploadFile, File

from app.integrations.s3.upload_service import upload_image
from app.integrations.s3.media_helpers import client_media_urls


router = APIRouter(
    prefix="/test-upload",
    tags=["Test Upload"]
)


@router.post("/")
async def test_upload(
    file: UploadFile = File(...)
):

    image_url = await upload_image(
        file=file,
        folder="test-uploads"
    )

    return {
        "success": True,
        **client_media_urls(image_url),
    }