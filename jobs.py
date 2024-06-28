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

        self.stocks_order_sync_lambda_function = awslambda.Function(
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
        self.template.add_resource(self.stocks_order_sync_lambda_function)

        self.order_sync_api_resource = apigateway.Resource(
            "OrderSyncResource",
            ParentId="{{resolve:ssm:/stocks/sync/resource/id}}",
            RestApiId="{{resolve:ssm:/stocks/api/id}}",
            PathPart="orders",
        )
        self.template.add_resource(self.order_sync_api_resource)

        order_sync_api_method = apigateway.Method(
            "OrderSyncMethod",
            DependsOn=self.stocks_order_sync_lambda_function,
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
                    LambdaArn=GetAtt(self.stocks_order_sync_lambda_function, "Arn"),
                ),
            ),
        )
        self.template.add_resource(order_sync_api_method)

        self.template.add_resource(
            awslambda.Permission(
                "OrderSyncInvokePermission",
                DependsOn=self.stocks_order_sync_lambda_function,
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
                                    "Resource": "*",
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
            ScheduleExpression="cron(0 18 ? * MON-FRI *)",
            ScheduleExpressionTimezone="America/Los_Angeles",
            FlexibleTimeWindow=scheduler.FlexibleTimeWindow(
                Mode="OFF"
            ),
            Target=scheduler.Target(
                Arn=GetAtt(self.stocks_order_sync_lambda_function, "Arn"),
                Input='{"httpMethod": "POST", "path": "/sync/orders"}',
                RetryPolicy=scheduler.RetryPolicy(
                    MaximumEventAgeInSeconds=86400,
                    MaximumRetryAttempts=185
                ),
                RoleArn=GetAtt(scheduler_execution_role, "Arn")
            )
        )
        self.template.add_resource(order_sync_scheduler)

    def create_stock_profit_calculator_lambda(self):
        lambda_role = self.template.add_resource(
            iam.Role(
                "ProfitCalculatorLambdaExecutionRole",
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
                        PolicyName="ProfitCalculatorLambdaS3Policy",
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
                        PolicyName="ProfitCalculatorLambdaLogPolicy",
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
                                                "ProfitCalculatorLambdaName"
                                            ],
                                        )
                                    ],
                                },
                            ],
                        },
                    ),
                    iam.Policy(
                        PolicyName="ProfitCalculatorLambdaSecretsManagerPolicy",
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

        self.stocks_profit_calculator_lambda_function = awslambda.Function(
            "ProfitCalculatorLambdaFunction",
            FunctionName=self.get_variables()["env-dict"]["ProfitCalculatorLambdaName"],
            Code=awslambda.Code(
                S3Bucket=Ref(self.existing_stocks_bucket),
                S3Key=Sub(
                    "lambdas/${LambdaName}.zip",
                    LambdaName=self.get_variables()["env-dict"][
                        "ProfitCalculatorLambdaName"
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
        self.template.add_resource(self.stocks_profit_calculator_lambda_function)

        self.profit_calculator_api_resource = apigateway.Resource(
            "ProfitCalculatorResource",
            ParentId="{{resolve:ssm:/stocks/sync/resource/id}}",
            RestApiId="{{resolve:ssm:/stocks/api/id}}",
            PathPart="profit",
        )
        self.template.add_resource(self.profit_calculator_api_resource)

        profit_calculator_api_method = apigateway.Method(
            "ProfitCalculatorMethod",
            DependsOn=self.stocks_profit_calculator_lambda_function,
            AuthorizationType="NONE",
            ApiKeyRequired=True,
            HttpMethod="POST",
            RestApiId="{{resolve:ssm:/stocks/api/id}}",
            ResourceId=Ref(self.profit_calculator_api_resource),
            Integration=apigateway.Integration(
                IntegrationHttpMethod="POST",
                Type="AWS_PROXY",
                Uri=Sub(
                    "arn:aws:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/${LambdaArn}/invocations",
                    LambdaArn=GetAtt(self.stocks_profit_calculator_lambda_function, "Arn"),
                ),
            ),
        )
        self.template.add_resource(profit_calculator_api_method)

        self.template.add_resource(
            awslambda.Permission(
                "ProfitCalculatorInvokePermission",
                DependsOn=self.stocks_profit_calculator_lambda_function,
                Action="lambda:InvokeFunction",
                FunctionName=self.get_variables()["env-dict"][
                    "ProfitCalculatorLambdaName"
                ],
                Principal="apigateway.amazonaws.com",
                SourceArn=Sub(
                    "arn:aws:execute-api:${AWS::Region}:${AWS::AccountId}:${ApiId}/*/POST/sync/profit",
                    ApiId="{{resolve:ssm:/stocks/api/id}}",
                ),
            )
        )
    
    def create_profit_calculator_scheduler(self):
        scheduler_execution_role = self.template.add_resource(
            iam.Role(
                "ProfitCalculatorSchedulerExecutionRole",
                AssumeRolePolicyDocument={
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Principal": {
                                    "Service": "scheduler.amazonaws.com"
                                },
                                "Action": "sts:AssumeRole",
                            }
                        ]
                },
                Policies=[
                    iam.Policy(
                        PolicyName="ProfitCalculatorSchedulerExecutionPolicy",
                        PolicyDocument={
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": ["lambda:InvokeFunction"],
                                    "Resource": "*",
                                },
                            ],
                        },
                    )
                ]
            )
        )

        profit_calculator_scheduler = scheduler.Schedule(
            "ProfitCalculatorScheduler",
            Name="profit-calculator-scheduler",
            Description="Profit Calculator Scheduler",
            ScheduleExpression="cron(0 19 ? * MON-FRI *)",
            ScheduleExpressionTimezone="America/Los_Angeles",
            FlexibleTimeWindow=scheduler.FlexibleTimeWindow(
                Mode="OFF"
            ),
            Target=scheduler.Target(
                Arn=GetAtt(self.stocks_profit_calculator_lambda_function, "Arn"),
                Input='{"httpMethod": "POST", "path": "/sync/profit"}',
                RetryPolicy=scheduler.RetryPolicy(
                    MaximumEventAgeInSeconds=86400,
                    MaximumRetryAttempts=185
                ),
                RoleArn=GetAtt(scheduler_execution_role, "Arn")
            )
        )
        self.template.add_resource(profit_calculator_scheduler)



    def create_stocks_cancel_lambda(self):
        lambda_role = self.template.add_resource(
            iam.Role(
                "CancelOrdersLambdaExecutionRole",
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
                        PolicyName="CancelOrdersLambdaS3Policy",
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
                        PolicyName="CancelOrdersLambdaLogPolicy",
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
                                                "CancelOrdersLambdaName"
                                            ],
                                        )
                                    ],
                                },
                            ],
                        },
                    ),
                    iam.Policy(
                        PolicyName="CancelOrdersLambdaSecretsManagerPolicy",
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

        self.stocks_cancel_lambda_function = awslambda.Function(
            "CancelOrdersLambdaFunction",
            FunctionName=self.get_variables()["env-dict"]["CancelOrdersLambdaName"],
            Code=awslambda.Code(
                S3Bucket=Ref(self.existing_stocks_bucket),
                S3Key=Sub(
                    "lambdas/${LambdaName}.zip",
                    LambdaName=self.get_variables()["env-dict"][
                        "CancelOrdersLambdaName"
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
        self.template.add_resource(self.stocks_cancel_lambda_function)

        self.cancel_orders_api_resource = apigateway.Resource(
            "CancelOrdersResource",
            ParentId="{{resolve:ssm:/stocks/sync/resource/id}}",
            RestApiId="{{resolve:ssm:/stocks/api/id}}",
            PathPart="cancel",
        )
        self.template.add_resource(self.cancel_orders_api_resource)

        cancel_orders_api_method = apigateway.Method(
            "CancelOrdersMethod",
            DependsOn=self.stocks_cancel_lambda_function,
            AuthorizationType="NONE",
            ApiKeyRequired=True,
            HttpMethod="POST",
            RestApiId="{{resolve:ssm:/stocks/api/id}}",
            ResourceId=Ref(self.profit_calculator_api_resource),
            Integration=apigateway.Integration(
                IntegrationHttpMethod="POST",
                Type="AWS_PROXY",
                Uri=Sub(
                    "arn:aws:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/${LambdaArn}/invocations",
                    LambdaArn=GetAtt(self.stocks_cancel_lambda_function, "Arn"),
                ),
            ),
        )
        self.template.add_resource(cancel_orders_api_method)

        self.template.add_resource(
            awslambda.Permission(
                "CancelOrdersInvokePermission",
                DependsOn=self.stocks_cancel_lambda_function,
                Action="lambda:InvokeFunction",
                FunctionName=self.get_variables()["env-dict"][
                    "CancelOrdersLambdaName"
                ],
                Principal="apigateway.amazonaws.com",
                SourceArn=Sub(
                    "arn:aws:execute-api:${AWS::Region}:${AWS::AccountId}:${ApiId}/*/POST/sync/cancel",
                    ApiId="{{resolve:ssm:/stocks/api/id}}",
                ),
            )
        )

    def create_stocks_cancel_scheduler(self):
        scheduler_execution_role = self.template.add_resource(
            iam.Role(
                "CancelOrdersSchedulerExecutionRole",
                AssumeRolePolicyDocument={
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Principal": {
                                    "Service": "scheduler.amazonaws.com"
                                },
                                "Action": "sts:AssumeRole",
                            }
                        ]
                },
                Policies=[
                    iam.Policy(
                        PolicyName="CancelOrdersSchedulerExecutionPolicy",
                        PolicyDocument={
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": ["lambda:InvokeFunction"],
                                    "Resource": "*",
                                },
                            ],
                        },
                    )
                ]
            )
        )

        cancel_orders_scheduler = scheduler.Schedule(
            "CancelOrdersScheduler",
            Name="cancel-orders-scheduler",
            Description="Cancel orders Scheduler",
            ScheduleExpression="cron(40 17 ? * MON-FRI *)",
            ScheduleExpressionTimezone="America/Los_Angeles",
            FlexibleTimeWindow=scheduler.FlexibleTimeWindow(
                Mode="OFF"
            ),
            Target=scheduler.Target(
                Arn=GetAtt(self.stocks_cancel_lambda_function, "Arn"),
                Input='{"httpMethod": "POST", "path": "/sync/cancel"}',
                RetryPolicy=scheduler.RetryPolicy(
                    MaximumEventAgeInSeconds=86400,
                    MaximumRetryAttempts=185
                ),
                RoleArn=GetAtt(scheduler_execution_role, "Arn")
            )
        )
        self.template.add_resource(cancel_orders_scheduler)

    def create_template(self):
        self.get_existing_stocks_bucket()
        self.create_stocks_order_sync_lambda()
        self.create_order_sync_scheduler()
        self.create_stock_profit_calculator_lambda()
        self.create_profit_calculator_scheduler()
        self.create_stocks_cancel_lambda()
        self.create_stocks_cancel_scheduler()
        return self.template
