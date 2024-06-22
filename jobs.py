from stacker.blueprints.base import Blueprint
from troposphere import (
    Ref,
    GetAtt,
    iam,
    awslambda,
    Parameter,
    Sub,
    apigateway,
    scheduler
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

    def create_stocks_order_sync_lambda(self):
        lambda_role = self.template.add_resource(
            iam.Role(
                "OrderSyncLambdaExecutionRole",
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
                        PolicyName="OrderSyncLambdaS3Policy",
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
                        PolicyName="OrderSyncLambdaLogPolicy",
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
                                                "OrderSyncLambdaName"
                                            ],
                                        )
                                    ],
                                },
                            ],
                        },
                    ),
                    iam.Policy(
                        PolicyName="OrderSyncLambdaSecretsManagerPolicy",
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

        stocks_order_sync_lambda_function = awslambda.Function(
            "OrderSyncLambdaFunction",
            FunctionName=self.get_variables()["env-dict"]["OrderSyncLambdaName"],
            Code=awslambda.Code(
                S3Bucket=Ref(self.existing_stocks_bucket),
                S3Key=Sub(
                    "lambdas/${LambdaName}.zip",
                    LambdaName=self.get_variables()["env-dict"][
                        "OrderSyncLambdaName"
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
            Handler="handler",
            Runtime="provided.al2023",
            Role=GetAtt(lambda_role, "Arn"),
        )
        self.template.add_resource(stocks_order_sync_lambda_function)

        self.order_sync_api_resource = apigateway.Resource(
            "OrderSyncResource",
            ParentId="{{resolve:ssm:/stocks/sync/resource/id}}",
            RestApiId="{{resolve:ssm:/stocks/api/id}}",
            PathPart="orders",
        )
        self.template.add_resource(self.order_sync_api_resource)

        order_sync_api_method = apigateway.Method(
            "OrderSyncMethod",
            DependsOn=stocks_order_sync_lambda_function,
            AuthorizationType="NONE",
            ApiKeyRequired=True,
            HttpMethod="POST",
            RestApiId="{{resolve:ssm:/stocks/api/id}}",
            ResourceId=Ref(self.order_sync_api_resource),
            Integration=apigateway.Integration(
                IntegrationHttpMethod="POST",
                Type="AWS_PROXY",
                Uri=Sub(
                    "arn:aws:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/${LambdaArn}/invocations",
                    LambdaArn=GetAtt(stocks_order_sync_lambda_function, "Arn"),
                ),
            ),
        )
        self.template.add_resource(order_sync_api_method)

        self.template.add_resource(
            awslambda.Permission(
                "OrderSyncInvokePermission",
                DependsOn=stocks_order_sync_lambda_function,
                Action="lambda:InvokeFunction",
                FunctionName=self.get_variables()["env-dict"][
                    "OrderSyncLambdaName"
                ],
                Principal="apigateway.amazonaws.com",
                SourceArn=Sub(
                    "arn:aws:execute-api:${AWS::Region}:${AWS::AccountId}:${ApiId}/*/POST/sync/orders",
                    ApiId="{{resolve:ssm:/stocks/api/id}}",
                ),
            )
        )

    def create_order_sync_scheduler(self):
        scheduler_execution_role = self.template.add_resource(
            iam.Role(
                "OrderSyncSchedulerExecutionRole",
                AssumeRolePolicyDocument={
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Principal": {
                                    "Service": "scheduler.amazonaws.com"
                                },
                                "Action": "sts:AssumeRole",
                                "Condition": {
                                    "StringEquals": {
                                        "aws:SourceArn": Sub("arn:aws:scheduler:{AWS::Region}:{AWS::AccountId}:schedule/default/{LambdaName}",                     
                                            LambdaName=self.get_variables()["env-dict"]["OrderSyncLambdaName"]
                                        ),
                                        "aws:SourceAccount": Sub("{AWS::AccountId}"),
                                    }
                                }
                            }
                        ]
                },
                Policies=[
                    iam.Policy(
                        PolicyName="OrderSyncSchedulerExecutionPolicy",
                        PolicyDocument={
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": ["lambda:InvokeFunction"],
                                    "Resource": [
                                        Sub(
                                            "{LambdaArn}:*",
                                            LambdaArn=GetAtt(
                                                self.order_sync_api_resource,
                                                "Arn",
                                            ),
                                        ),
                                        Sub(
                                            "{LambdaArn}",
                                            LambdaArn=GetAtt(
                                                self.order_sync_api_resource,
                                                "Arn",
                                            ),
                                        )
                                    ],
                                },
                            ],
                        },
                    )
                ]
            )
        )

        order_sync_scheduler = scheduler.Schedule(
            "OrderSyncScheduler",
            Name="order-sync-scheduler",
            Description="Order Sync Scheduler",
            ScheduleExpression="cron(0 0 * * ? *)",
            ScheduleExpressionTimezone="America/Los_Angeles",
            FlexibleTimeWindow=scheduler.FlexibleTimeWindow(
                Mode="OFF"
            ),
            Target=scheduler.Target(
                Arn=GetAtt(self.order_sync_api_resource, "Arn"),
                Input='{"httpMethod": "POST", "path": "/sync/orders"}',
                RetryPolicy=scheduler.RetryPolicy(
                    MaximumEventAgeInSeconds=86400,
                    MaximumRetryAttempts=185
                ),
                RoleArn=GetAtt(scheduler_execution_role, "Arn")
            )
        )
        self.template.add_resource(order_sync_scheduler)


    def create_template(self):
        self.get_existing_stocks_bucket()
        self.create_stocks_order_sync_lambda()
        self.create_order_sync_scheduler()
        return self.template
