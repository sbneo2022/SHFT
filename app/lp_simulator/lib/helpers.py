from datetime import datetime

import boto3
from botocore.config import Config


def bp_print(x, precision=1):
    return str(round(1e4 * x, 1)) + " bp"


def list_s3_dir(bucket, path):
    """
        Lists all S3 objects which are inside this path. Similar to listing
        files in a directory.
        IMPORTANT: Directories will not be listed. They are not S3 objects.

    Parameters:
        bucket: string representing the s3 bucket
        path: string prefix
    Returns:
        all_keys([str, str,...]): a list containing full S3 uri
    """

    config = Config(connect_timeout=5)
    s3 = boto3.resource("s3", config=config)
    bucket_obj = s3.Bucket(bucket)

    hard_prefix = path if path.endswith("/") else path + "/"
    all_keys = [
        "s3://{bucket}/{key}".format(bucket=summary.bucket_name, key=summary.key)
        for summary in bucket_obj.objects.filter(Prefix=hard_prefix)
    ]
    return all_keys


def pretty_date(time):
    """
    Get a datetime object or a int() Epoch timestamp and return a
    pretty string like 'an hour', 'Yesterday', '3 months',
    'just now', etc
    """

    second_diff = round(time, 2)
    day_diff = int(time / (60 * 60 * 24))

    if day_diff < 0:
        return ""

    if day_diff == 0:
        if second_diff < 10:
            return "just now"
        if second_diff < 60:
            return round(str(second_diff), 1) + " seconds"
        if second_diff < 120:
            return "a minute"
        if second_diff < 3600:
            return str(round(second_diff / 60, 1)) + " minutes"
        if second_diff < 7200:
            return "an hour"
        if second_diff < 86400:
            return str(round(second_diff / 3600, 1)) + " hours"

    if day_diff == 1:
        return "Yesterday"
    if day_diff < 7:
        return str(day_diff) + " days"
    if day_diff < 31:
        return str(day_diff // 7) + " weeks"
    if day_diff < 365:
        return str(day_diff // 30) + " months"
    return str(day_diff // 365) + " years"
