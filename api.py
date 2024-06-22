from stacker.blueprints.base import Blueprint
from troposphere import Output, Ref, apigateway, GetAtt, ssm


class Stocks(Blueprint):
    VARIABLES = {"env-dict": {"type": dict}}

    def create_api_gateway(self):
        self.api = apigateway.RestApi(
            "StocksApi",
            Name=self.get_variables()["env-dict"]["ApiName"],
            ApiKeySourceType="HEADER",
            EndpointConfiguration=apigateway.EndpointConfiguration(Types=["REGIONAL"]),
        )
        self.template.add_resource(self.api)

        self.webhook_api_resource = apigateway.Resource(
            "WebhookResource",
            ParentId=GetAtt(self.api, "RootResourceId"),
            RestApiId=Ref(self.api),
            PathPart="webhook",
        )
        self.template.add_resource(self.webhook_api_resource)

        self.sync_api_resource = apigateway.Resource(
            "SyncResource",
            ParentId=GetAtt(self.api, "RootResourceId"),
            RestApiId=Ref(self.api),
            PathPart="sync",
        )
        self.template.add_resource(self.sync_api_resource)

        self.template.add_output(
            Output(
                "StocksApiId",
                Value=Ref(self.api),
            )
        )

    def store_ssm_parameters(self):
        ssm_api_id = ssm.Parameter(
            "StocksApiId",
            Name="/stocks/api/id",
            Type="String",
            Value=Ref(self.api),
        )
        self.template.add_resource(ssm_api_id)

        ssm_api_parent_resource_id = ssm.Parameter(
            "StocksApiParentResourceId",
            Name="/stocks/api/parent/resource/id",
            Type="String",
            Value=GetAtt(self.api, "RootResourceId"),
        )
        self.template.add_resource(ssm_api_parent_resource_id)

        ssm_webhook_resource_id = ssm.Parameter(
            "WebhookResourceId",
            Name="/stocks/webhook/resource/id",
            Type="String",
            Value=Ref(self.webhook_api_resource),
        )
        self.template.add_resource(ssm_webhook_resource_id)

        ssm_sync_resource_id = ssm.Parameter(
            "SyncResourceId",
            Name="/stocks/sync/resource/id",
            Type="String",
            Value=Ref(self.sync_api_resource),
        )
        self.template.add_resource(ssm_sync_resource_id)

    def create_template(self):
        self.create_api_gateway()
        self.store_ssm_parameters()
        return self.template
