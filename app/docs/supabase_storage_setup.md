# Supabase Storage (media uploads)

CoBrother uses **Supabase Storage** via the **S3-compatible API** (not AWS S3).

## Dashboard setup

1. Open [Supabase](https://supabase.com) → your project.
2. **Storage** → create a bucket (e.g. `cobrother-media`).
3. Bucket may be **private**; the backend signs URLs when returning `imageUrl` to the UI.
   For direct browser testing you can still mark the bucket public if you prefer.
4. **Project Settings** → **Storage** → **S3 Connection**:
   - Copy **Access Key ID**, **Secret Access Key**, and **Region**.
   - Note the S3 endpoint (optional; auto-derived from `SUPABASE_URL`).

## Backend `.env`

```env
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_STORAGE_BUCKET=cobrother-media
SUPABASE_S3_ACCESS_KEY_ID=<from S3 Connection>
SUPABASE_S3_SECRET_ACCESS_KEY=<from S3 Connection>
SUPABASE_S3_REGION=ap-south-1
```

Public file URL shape:

`https://<project-ref>.supabase.co/storage/v1/object/public/<bucket>/<folder>/<file>`

## Test upload

With the API running:

```bash
curl -X POST http://127.0.0.1:8000/test-upload/ \
  -F "file=@/path/to/image.png"
```

Returns `{ "imageUrl": "https://..." }`.

## Legacy `AWS_*` env vars

Still supported as aliases for the Supabase S3 keys and bucket name, but **`SUPABASE_URL` is required**.
