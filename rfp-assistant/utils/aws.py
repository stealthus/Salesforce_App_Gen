import io
import os
import json
import logging
import git
import boto3
from botocore.exceptions import ClientError
from typing import Dict, Any, Optional
from .generate_id import generate_id

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DirectS3Uploader:
    def __init__(self, aws_access_key=None, aws_secret_key=None, region="us-east-1"):
        """
        Initialize the S3 uploader with AWS credentials.
        If not provided, will use environment variables or AWS CLI configuration.
        """
        self.s3_client = boto3.client(
            's3',
            aws_access_key_id="0fb0af7f4f7747d48eeb5bc306fba61a",
            aws_secret_access_key="201bdd6c55ae8f843ed3d78464b9174f1d4d3c96aa21da80274c631d567d15f0",
            region_name='auto',
            endpoint_url= 'https://b84c34412e184b50a671d3b3ec1971cd.r2.cloudflarestorage.com' 
        )
    
    def upload_to_s3(self, repo_url: str, bucket_name: str = "vercel", prefix: str = None) -> Dict[str, Any]:
        """
        Clone a GitHub repository and upload directly to S3 bucket
        without storing the full repository locally.
        
        Args:
            repo_url: URL of the GitHub repository to clone
            bucket_name: Name of the S3 bucket to upload to
            prefix: Prefix (folder) to use in the S3 bucket
            
        Returns:
            Dict containing information about the upload process
        """
        # Extract repo information
        parts = repo_url.strip("/").split("/")
        repo_name = f"{parts[-2]}/{parts[-1]}"
        
        # Generate a workspace ID for S3 folder
        workspace_id = generate_id()
        
        # Set the prefix (folder) in S3
        if not prefix:
            prefix = workspace_id
            
        # Create response structure
        result = {
            "repo_url": repo_url,
            "repo_name": repo_name,
            "workspace_id": workspace_id,
            "s3_bucket": bucket_name,
            "s3_prefix": prefix,
            "files": [],
            "folders": [],
            "uploaded_files": 0,
            "error": None
        }
        
        try:
            # Clone repository to a temporary in-memory representation
            logger.info(f"Processing repository {repo_url}")
            
            # Use GitPython to efficiently process the repository
            repo = git.Repo.clone_from(repo_url, "/tmp/temp_repo_" + workspace_id, depth=1)
            
            # Track unique folders
            unique_folders = set()
            
            # Process each file in the repository
            for item in repo.tree().traverse():
                # Skip if it's not a blob (file)
                if not isinstance(item, git.Blob):
                    continue
                
                # Get the file path
                file_path = item.path
                
                # Skip .git files
                if '.git' in file_path:
                    continue
                
                # Add file to result
                result["files"].append(file_path)
                
                # Extract folder path and add to folders
                folder_path = os.path.dirname(file_path)
                if folder_path:
                    parts = folder_path.split(os.sep)
                    # Add all parent folders
                    current = ""
                    for part in parts:
                        if current:
                            current = os.path.join(current, part)
                        else:
                            current = part
                        unique_folders.add(current)
                
                # Read file content directly from git
                file_content = item.data_stream.read()
                
                # Create S3 key
                s3_key = f"{prefix}/{file_path}"
                
                # Upload file to S3 directly from memory
                try:
                    self.s3_client.put_object(
                        Bucket=bucket_name,
                        Key=s3_key,
                        Body=file_content
                    )
                    result["uploaded_files"] += 1
                    logger.info(f"Uploaded {file_path} to S3")
                except ClientError as e:
                    logger.error(f"Error uploading {file_path}: {e}")
                    if not result["error"]:
                        result["error"] = f"Error uploading files: {str(e)}"
            
            # Add folders to result
            result["folders"] = list(unique_folders)
            
            logger.info(f"Uploaded {result['uploaded_files']} files to S3 bucket {bucket_name}/{prefix}")
            
        except git.exc.GitCommandError as e:
            error_msg = f"Git clone failed: {str(e)}"
            logger.error(error_msg)
            result["error"] = error_msg
        except Exception as e:
            error_msg = f"Error processing repository: {str(e)}"
            logger.error(error_msg)
            result["error"] = error_msg
        finally:
            # Clean up
            try:
                if os.path.exists("/tmp/temp_repo_" + workspace_id):
                    import shutil
                    shutil.rmtree("/tmp/temp_repo_" + workspace_id)
            except:
                pass
        
        return result

def upload_repo_to_s3(repo_url: str, bucket_name: str = "vercel", prefix: str = None, 
                   aws_access_key: str = None, aws_secret_key: str = None, 
                   region: str = "us-east-1") -> Dict[str, Any]:
    """
    Clone a GitHub repository and upload directly to S3.
    
    Args:
        repo_url: URL of the GitHub repository to clone
        bucket_name: Name of the S3 bucket to upload to
        prefix: Prefix (folder) to use in the S3 bucket (defaults to generated workspace ID)
        aws_access_key: AWS access key ID
        aws_secret_key: AWS secret access key
        region: AWS region
        
    Returns:
        Dict containing information about the upload process
    """
    uploader = DirectS3Uploader(aws_access_key, aws_secret_key, region)
    return uploader.upload_to_s3(repo_url, bucket_name, prefix)

def print_s3_upload_result(result: Dict[str, Any]):
    """
    Print a summary of the S3 upload process
    """
    print("\nS3 UPLOAD SUMMARY:")
    print(f"Repository: {result['repo_name']} ({result['repo_url']})")
    print(f"S3 Bucket: {result['s3_bucket']}")
    print(f"S3 Prefix: {result['s3_prefix']}")
    print(f"Files Uploaded: {result['uploaded_files']} of {len(result['files'])} files")
    print(f"Folders Created: {len(result['folders'])}")
    
    # Print sample of uploaded files
    if result['files']:
        print("\nSample files uploaded:")
        for file in sorted(result['files'])[:5]:
            print(f"  📄 {file}")
        if len(result['files']) > 5:
            print("  ...")
    
    if result['error']:
        print(f"\nERROR: {result['error']}")

if __name__ == "__main__":
    # Example usage
    repo_url = "https://github.com/rasbt/watermark"
    bucket_name = "vercel"
    
    # Upload repository to S3
    result = upload_repo_to_s3(
        repo_url=repo_url,
        bucket_name=bucket_name,
        # Credentials can be set here or via environment variables
        aws_access_key="0fb0af7f4f7747d48eeb5bc306fba61a",
        aws_secret_key="201bdd6c55ae8f843ed3d78464b9174f1d4d3c96aa21da80274c631d567d15f0",
        region="US"
    )
    
    # Print results
    print_s3_upload_result(result)