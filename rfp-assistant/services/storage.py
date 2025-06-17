"""
Storage service for handling document uploads and retrieval.
Integrates with AWS S3 for cloud storage.
"""
import os
import uuid
import tempfile
from fastapi import UploadFile
from utils.aws import DirectS3Uploader
import boto3
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class StorageService:
    def __init__(self):
        """Initialize storage service with S3 configuration"""
        self.aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")
        self.aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        self.region = os.getenv("AWS_REGION")
        self.bucket_name = os.getenv("AWS_BUCKET_NAME", "vercel")
        self.endpoint_url = os.getenv("AWS_ENDPOINT_URL")
        
        # Initialize S3 client
        self.s3_client = boto3.client(
            's3',
            aws_access_key_id=self.aws_access_key,
            aws_secret_access_key=self.aws_secret_key,
            region_name='auto',
            endpoint_url=self.endpoint_url
        )
        
        # Initialize S3 uploader
        self.uploader = DirectS3Uploader(
            aws_access_key=self.aws_access_key,
            aws_secret_key=self.aws_secret_key,
            region=self.region
        )
    
    async def upload_file(self, file: UploadFile) -> str:
        """
        Upload a file to S3 storage
        
        Args:
            file: The uploaded file object
            
        Returns:
            str: The S3 key for the uploaded file (UUID-based)
        """
        # Generate a unique file ID
        file_id = str(uuid.uuid4())
        
        # Get file extension
        _, ext = os.path.splitext(file.filename)
        
        # Create S3 key with UUID only and extension
        s3_key = f"rfp-documents/{file_id}{ext}"
        
        # Save file to temporary location
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as temp_file:
            # Write uploaded file content to temp file
            content = await file.read()
            temp_file.write(content)
            temp_path = temp_file.name
        
        try:
            # Upload to S3 with metadata for original filename
            self.s3_client.upload_file(
                temp_path,
                self.bucket_name,
                s3_key,
                ExtraArgs={
                    'Metadata': {
                        'original_filename': file.filename
                    }
                }
            )
            
            # Clean up temp file
            os.unlink(temp_path)
            
            return s3_key
        except Exception as e:
            # Clean up temp file in case of error
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise e
    
    def download_file(self, s3_key: str) -> str:
        """
        Download a file from S3 storage
        
        Args:
            s3_key: The S3 key for the file
            
        Returns:
            str: The local path to the downloaded file
        """
        # Extract filename from S3 key
        filename = os.path.basename(s3_key)
        
        # Create temp file with same extension
        _, ext = os.path.splitext(filename)
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
        temp_path = temp_file.name
        temp_file.close()
        
        try:
            # Download from S3
            self.s3_client.download_file(
                self.bucket_name,
                s3_key,
                temp_path
            )
            
            return temp_path
        except Exception as e:
            # Clean up temp file in case of error
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise e

# Create singleton instance
storage_service = StorageService()
