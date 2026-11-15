import boto3
from dotenv import load_dotenv
load_dotenv()
s3 = boto3.client("s3")

response = s3.list_buckets()

for bucket in response["Buckets"]:
    print(bucket["Name"])