from stacker.blueprints.base import Blueprint
from troposphere import (
    Output,
    Ref,
    s3,
)


class Stocks(Blueprint):
    VARIABLES = {"env-dict": {"type": dict}}

    def create_template(self):
        s3_bucket = s3.Bucket(
            "StockS3Bucket",
            BucketName=self.get_variables()["env-dict"]["BucketName"],
        )
        self.template.add_resource(s3_bucket)

        self.template.add_output(
            Output(
                "BucketName",
                Value=Ref(s3_bucket),
            )
        )