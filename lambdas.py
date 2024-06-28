from stacker.blueprints.base import Blueprint
from troposphere import (
    Ref,
    GetAtt,
    iam,
    awslambda,
    Parameter,
    Sub,
    apigateway,
)


class Stocks(Blueprint):
    VARIABLES = {"env-dict": {"type": dict}}

    def get_existing_stocks_bucket(self):
        self.existing_stocks_bucket = self.template.add_parameter(
            Parameter(
                "StockS3Bucket",
                Type="String",
                Default=self.get_variables()["env-dict"]["BucketName"],
            )
        )

    def create_stocks_pattern_lambda(self):
        lambda_role = self.template.add_resource(
            iam.Role(
                "StocksPatternLambdaExecutionRole",
                AssumeRolePolicyDocument={
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {
                                "Service": [
                                    "lambda.amazonaws.com",
                                    "apigateway.amazonaws.com",
                                ]
                            },
                            "Action": ["sts:AssumeRole"],
                        }
                    ],
                },
                Policies=[
                    iam.Policy(
                        PolicyName="StocksPatternLambdaS3Policy",
                        PolicyDocument={
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": ["s3:GetObject"],
                                    "Resource": [
                                        Sub(
                                            "arn:aws:s3:::${BucketName}/*",
                                            BucketName=self.get_variables()["env-dict"][
                                                "BucketName"
                                            ],
                                        )
                                    ],
                                }
                            ],
                        },
                    ),
                    iam.Policy(
                        PolicyName="StocksPatternLambdaLogPolicy",
                        PolicyDocument={
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": "logs:CreateLogGroup",
                                    "Resource": Sub(
                                        "arn:aws:logs:${AWS::Region}:${AWS::AccountId}:*"
                                    ),
                                },
                                {
                                    "Effect": "Allow",
                                    "Action": [
                                        "logs:CreateLogStream",
                                        "logs:PutLogEvents",
                                    ],
                                    "Resource": [
                                        Sub(
                                            "arn:aws:logs:${AWS::Region}:${AWS::AccountId}:log-group:/aws/lambda/${LambdaName}:*",
                                            LambdaName=self.get_variables()["env-dict"][
                                                "StocksPatternLambdaName"
                                            ],
                                        )
                                    ],
                                },
                            ],
                        },
                    ),
                    iam.Policy(
                        PolicyName="StocksPatternLambdaSecretsManagerPolicy",
                        PolicyDocument={
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": ["secretsmanager:GetSecretValue"],
                                    "Resource": [
                                        Sub(
                                            "arn:aws:secretsmanager:${AWS::Region}:${AWS::AccountId}:secret:${SecretId}-5BII06",
                                            SecretId=self.get_variables()["env-dict"][
                                                "SharedSecretsId"
                                            ],
                                        )
                                    ],
                                }
                            ],
                        },
                    ),
                ],
            )
        )

        stocks_pattern_lambda_function = awslambda.Function(
            "StocksPatternLambdaFunction",
            FunctionName=self.get_variables()["env-dict"]["StocksPatternLambdaName"],
            Code=awslambda.Code(
                S3Bucket=Ref(self.existing_stocks_bucket),
                S3Key=Sub(
                    "lambdas/${LambdaName}.zip",
                    LambdaName=self.get_variables()["env-dict"][
                        "StocksPatternLambdaName"
                    ],
                ),
            ),
            Environment=awslambda.Environment(
                Variables={
                    "SHARED_SECRETS": self.get_variables()["env-dict"][
                        "SharedSecretsId"
                    ]
                }
            ),
            Timeout=300,
            Handler="handler",
            Runtime="provided.al2023",
            Role=GetAtt(lambda_role, "Arn"),
        )
        self.template.add_resource(stocks_pattern_lambda_function)

        self.harmonic_pattern_api_resource = apigateway.Resource(
            "HarmonicPatternResource",
            ParentId="{{resolve:ssm:/stocks/webhook/resource/id}}",
            RestApiId="{{resolve:ssm:/stocks/api/id}}",
            PathPart="harmonic-pattern",
        )
        self.template.add_resource(self.harmonic_pattern_api_resource)

        harmonic_pattern_api_method = apigateway.Method(
            "HarmonicPatternMethod",
            DependsOn=stocks_pattern_lambda_function,
            AuthorizationType="NONE",
            ApiKeyRequired=False,
            HttpMethod="POST",
            RestApiId="{{resolve:ssm:/stocks/api/id}}",
            ResourceId=Ref(self.harmonic_pattern_api_resource),
            Integration=apigateway.Integration(
                IntegrationHttpMethod="POST",
                Type="AWS_PROXY",
                Uri=Sub(
                    "arn:aws:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/${LambdaArn}/invocations",
                    LambdaArn=GetAtt(stocks_pattern_lambda_function, "Arn"),
                ),
            ),
        )
        self.template.add_resource(harmonic_pattern_api_method)

        self.template.add_resource(
            awslambda.Permission(
                "StocksPatternInvokePermission",
                DependsOn=stocks_pattern_lambda_function,
                Action="lambda:InvokeFunction",
                FunctionName=self.get_variables()["env-dict"][
                    "StocksPatternLambdaName"
                ],
                Principal="apigateway.amazonaws.com",
                SourceArn=Sub(
                    "arn:aws:execute-api:${AWS::Region}:${AWS::AccountId}:${ApiId}/*/POST/webhook/harmonic-pattern",
                    ApiId="{{resolve:ssm:/stocks/api/id}}",
                ),
            )
        )

    def create_template(self):
        self.get_existing_stocks_bucket()
        self.create_stocks_pattern_lambda()
        return self.template
