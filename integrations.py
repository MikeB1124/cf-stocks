from stacker.blueprints.base import Blueprint
from troposphere import (
    Ref,
    apigateway,
)


class Stocks(Blueprint):
    VARIABLES = {"env-dict": {"type": dict}}

    def create_template(self):
        stocks_api_deployment = self.template.add_resource(
            apigateway.Deployment(
                "StocksApiDeployment",
                RestApiId="{{resolve:ssm:/stocks/api/id}}",
            )
        )

        stocks_api_stage = self.template.add_resource(
            apigateway.Stage(
                "StocksApiStage",
                DeploymentId=Ref(stocks_api_deployment),
                RestApiId="{{resolve:ssm:/stocks/api/id}}",
                StageName="api",
            )
        )

        stocks_usage_plan = self.template.add_resource(
            apigateway.UsagePlan(
                "StocksUsagePlan",
                DependsOn=stocks_api_stage,
                UsagePlanName=self.get_variables()["env-dict"]["ApiUsagePlanName"],
                ApiStages=[
                    apigateway.ApiStage(
                        ApiId="{{resolve:ssm:/stocks/api/id}}",
                        Stage="api",
                    )
                ],
                Description="Stocks Usage Plan",
                Quota=apigateway.QuotaSettings(
                    Limit=100000,
                    Period="MONTH",
                ),
                Throttle=apigateway.ThrottleSettings(
                    BurstLimit=100,
                    RateLimit=50,
                ),
            )
        )

        stocks_api_key = self.template.add_resource(
            apigateway.ApiKey(
                "StocksApiKey",
                Name=self.get_variables()["env-dict"]["ApiKeyName"],
                Enabled=True,
            )
        )

        self.template.add_resource(
            apigateway.UsagePlanKey(
                "StocksUsagePlanKey",
                DependsOn=stocks_usage_plan,
                KeyId=Ref(stocks_api_key),
                KeyType="API_KEY",
                UsagePlanId=Ref(stocks_usage_plan),
            )
        )
