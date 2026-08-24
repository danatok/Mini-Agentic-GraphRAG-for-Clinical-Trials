"""Delete every billable/active AWS resource this project created.

Local files (data/, lambda/ source, the FAISS index, the networkx graph
pickle) are left untouched — this only tears down cloud resources:
  - Lambda functions: clinical-graphrag-graph-query, clinical-graphrag-vector-search
  - Their CloudWatch log groups (Lambda creates these automatically with no
    retention/expiry policy — deleting a function does NOT delete its log
    group, so it silently persists otherwise)
  - IAM roles: clinical-graphrag-demo-lambda-role, clinical-graphrag-demo-agent-role
    (with their attached/inline policies detached first)

Run this once demo output is captured — see README.md's example queries,
which were generated before teardown.
"""
import boto3

REGION = "us-east-1"
LAMBDA_FUNCTIONS = ["clinical-graphrag-graph-query", "clinical-graphrag-vector-search"]
IAM_ROLES = ["clinical-graphrag-demo-lambda-role", "clinical-graphrag-demo-agent-role"]

lambda_client = boto3.client("lambda", region_name=REGION)
iam = boto3.client("iam", region_name=REGION)
logs_client = boto3.client("logs", region_name=REGION)

deleted = []


def delete_lambda_functions() -> None:
    for name in LAMBDA_FUNCTIONS:
        try:
            lambda_client.delete_function(FunctionName=name)
            deleted.append(f"Lambda function: {name}")
            print(f"Deleted Lambda function {name}")
        except lambda_client.exceptions.ResourceNotFoundException:
            print(f"Lambda function {name} already gone, skipping")


def delete_log_groups() -> None:
    for name in LAMBDA_FUNCTIONS:
        log_group = f"/aws/lambda/{name}"
        try:
            logs_client.delete_log_group(logGroupName=log_group)
            deleted.append(f"CloudWatch log group: {log_group}")
            print(f"Deleted log group {log_group}")
        except logs_client.exceptions.ResourceNotFoundException:
            print(f"Log group {log_group} already gone, skipping")


def delete_iam_role(role_name: str) -> None:
    try:
        iam.get_role(RoleName=role_name)
    except iam.exceptions.NoSuchEntityException:
        print(f"IAM role {role_name} already gone, skipping")
        return

    for policy in iam.list_attached_role_policies(RoleName=role_name)["AttachedPolicies"]:
        iam.detach_role_policy(RoleName=role_name, PolicyArn=policy["PolicyArn"])
        print(f"  detached managed policy {policy['PolicyName']} from {role_name}")

    for policy_name in iam.list_role_policies(RoleName=role_name)["PolicyNames"]:
        iam.delete_role_policy(RoleName=role_name, PolicyName=policy_name)
        print(f"  deleted inline policy {policy_name} from {role_name}")

    iam.delete_role(RoleName=role_name)
    deleted.append(f"IAM role: {role_name}")
    print(f"Deleted IAM role {role_name}")


def main() -> None:
    delete_lambda_functions()
    delete_log_groups()
    for role_name in IAM_ROLES:
        delete_iam_role(role_name)

    print("\n" + "=" * 60)
    print("Teardown complete. Resources deleted this run:")
    for item in deleted:
        print(f"  - {item}")
    if not deleted:
        print("  (nothing to delete — already torn down)")
    print("\nNote: the AWS Budget alert (clinical-graphrag-demo-budget) is")
    print("intentionally left in place as an ongoing safety net.")
    print("=" * 60)


if __name__ == "__main__":
    main()
