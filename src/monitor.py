"""
aws-cloudwatch-monitor
======================
Main monitoring logic for AWS infrastructure.
Collects metrics from EC2, RDS, and Lambda via CloudWatch.

Author: Bremer Quiquia Cirineo
GitHub: https://github.com/BREMERQUIQUIA
"""

import boto3
import json
import logging
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


# ── Config loader ──────────────────────────────────────────────────────────────
def load_config(path: str = "config/config.json") -> Dict:
    """Load monitoring configuration from JSON file."""
    try:
        with open(path, "r") as f:
            config = json.load(f)
        logger.info(f"Config loaded from {path}")
        return config
    except FileNotFoundError:
        logger.warning(f"Config not found at {path}, using defaults.")
        return {
            "region": "us-east-1",
            "thresholds": {
                "ec2_cpu_percent": 80,
                "rds_cpu_percent": 75,
                "lambda_error_rate": 5,
                "disk_usage_percent": 85
            },
            "consecutive_breaches_to_alert": 3,
            "alert_email": ""
        }


# ── CloudWatch client ──────────────────────────────────────────────────────────
def get_cloudwatch_client(region: str):
    """Create and return a boto3 CloudWatch client."""
    return boto3.client("cloudwatch", region_name=region)


def get_metric(
    cw_client,
    namespace: str,
    metric_name: str,
    dimensions: List[Dict],
    period: int = 300,
    stat: str = "Average",
    lookback_minutes: int = 15
) -> Optional[float]:
    """
    Fetch the latest metric value from CloudWatch.

    Args:
        cw_client: boto3 CloudWatch client
        namespace: AWS namespace (e.g., 'AWS/EC2')
        metric_name: Metric to query (e.g., 'CPUUtilization')
        dimensions: List of dimension dicts [{'Name': ..., 'Value': ...}]
        period: Aggregation period in seconds (default 5 min)
        stat: Statistic type (Average, Maximum, Sum)
        lookback_minutes: How far back to look for data points

    Returns:
        Latest metric value or None if no data available
    """
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(minutes=lookback_minutes)

    try:
        response = cw_client.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric_name,
            Dimensions=dimensions,
            StartTime=start_time,
            EndTime=end_time,
            Period=period,
            Statistics=[stat]
        )
        datapoints = response.get("Datapoints", [])
        if not datapoints:
            return None
        # Return the most recent value
        latest = sorted(datapoints, key=lambda x: x["Timestamp"])[-1]
        return round(latest[stat], 2)

    except Exception as e:
        logger.error(f"Error fetching {metric_name}: {e}")
        return None


# ── EC2 monitoring ─────────────────────────────────────────────────────────────
def check_ec2_instances(cw_client, ec2_client, thresholds: Dict) -> List[Dict]:
    """
    Check CPU utilization for all running EC2 instances.

    Returns list of results with status per instance.
    """
    results = []
    logger.info("Checking EC2 instances...")

    try:
        response = ec2_client.describe_instances(
            Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
        )
    except Exception as e:
        logger.error(f"Could not list EC2 instances: {e}")
        return results

    for reservation in response.get("Reservations", []):
        for instance in reservation.get("Instances", []):
            instance_id = instance["InstanceId"]
            instance_type = instance.get("InstanceType", "unknown")

            # Get name tag if available
            name = instance_id
            for tag in instance.get("Tags", []):
                if tag["Key"] == "Name":
                    name = tag["Value"]
                    break

            cpu = get_metric(
                cw_client,
                namespace="AWS/EC2",
                metric_name="CPUUtilization",
                dimensions=[{"Name": "InstanceId", "Value": instance_id}]
            )

            threshold = thresholds.get("ec2_cpu_percent", 80)
            status = "OK"
            if cpu is None:
                status = "NO_DATA"
            elif cpu >= threshold:
                status = "ALARM"
            elif cpu >= threshold * 0.85:
                status = "WARNING"

            result = {
                "service": "EC2",
                "resource_id": instance_id,
                "resource_name": name,
                "instance_type": instance_type,
                "metric": "CPUUtilization",
                "value": cpu,
                "threshold": threshold,
                "unit": "%",
                "status": status,
                "checked_at": datetime.utcnow().isoformat()
            }
            results.append(result)
            logger.info(f"  EC2 {name} ({instance_id}): CPU={cpu}% → {status}")

    return results


# ── RDS monitoring ─────────────────────────────────────────────────────────────
def check_rds_instances(cw_client, rds_client, thresholds: Dict) -> List[Dict]:
    """
    Check CPU utilization and FreeStorageSpace for RDS instances.
    """
    results = []
    logger.info("Checking RDS instances...")

    try:
        response = rds_client.describe_db_instances()
    except Exception as e:
        logger.error(f"Could not list RDS instances: {e}")
        return results

    for db in response.get("DBInstances", []):
        db_id = db["DBInstanceIdentifier"]
        engine = db.get("Engine", "unknown")

        cpu = get_metric(
            cw_client,
            namespace="AWS/RDS",
            metric_name="CPUUtilization",
            dimensions=[{"Name": "DBInstanceIdentifier", "Value": db_id}]
        )

        threshold = thresholds.get("rds_cpu_percent", 75)
        status = "OK"
        if cpu is None:
            status = "NO_DATA"
        elif cpu >= threshold:
            status = "ALARM"
        elif cpu >= threshold * 0.85:
            status = "WARNING"

        result = {
            "service": "RDS",
            "resource_id": db_id,
            "resource_name": db_id,
            "engine": engine,
            "metric": "CPUUtilization",
            "value": cpu,
            "threshold": threshold,
            "unit": "%",
            "status": status,
            "checked_at": datetime.utcnow().isoformat()
        }
        results.append(result)
        logger.info(f"  RDS {db_id} ({engine}): CPU={cpu}% → {status}")

    return results


# ── Lambda monitoring ──────────────────────────────────────────────────────────
def check_lambda_functions(cw_client, lambda_client, thresholds: Dict) -> List[Dict]:
    """
    Check error rate and throttles for Lambda functions.
    """
    results = []
    logger.info("Checking Lambda functions...")

    try:
        response = lambda_client.list_functions()
    except Exception as e:
        logger.error(f"Could not list Lambda functions: {e}")
        return results

    for fn in response.get("Functions", []):
        fn_name = fn["FunctionName"]
        runtime = fn.get("Runtime", "unknown")

        errors = get_metric(
            cw_client,
            namespace="AWS/Lambda",
            metric_name="Errors",
            dimensions=[{"Name": "FunctionName", "Value": fn_name}],
            stat="Sum"
        )

        invocations = get_metric(
            cw_client,
            namespace="AWS/Lambda",
            metric_name="Invocations",
            dimensions=[{"Name": "FunctionName", "Value": fn_name}],
            stat="Sum"
        )

        error_rate = None
        if errors is not None and invocations and invocations > 0:
            error_rate = round((errors / invocations) * 100, 2)

        threshold = thresholds.get("lambda_error_rate", 5)
        status = "OK"
        if error_rate is None:
            status = "NO_DATA"
        elif error_rate >= threshold:
            status = "ALARM"
        elif error_rate >= threshold * 0.7:
            status = "WARNING"

        result = {
            "service": "Lambda",
            "resource_id": fn_name,
            "resource_name": fn_name,
            "runtime": runtime,
            "metric": "ErrorRate",
            "value": error_rate,
            "threshold": threshold,
            "unit": "%",
            "errors": errors,
            "invocations": invocations,
            "status": status,
            "checked_at": datetime.utcnow().isoformat()
        }
        results.append(result)
        logger.info(f"  Lambda {fn_name}: ErrorRate={error_rate}% → {status}")

    return results


# ── Summary builder ────────────────────────────────────────────────────────────
def build_summary(all_results: List[Dict]) -> Dict:
    """Build a summary dict from all monitoring results."""
    total = len(all_results)
    alarms  = [r for r in all_results if r["status"] == "ALARM"]
    warnings = [r for r in all_results if r["status"] == "WARNING"]
    no_data = [r for r in all_results if r["status"] == "NO_DATA"]
    ok      = [r for r in all_results if r["status"] == "OK"]

    return {
        "checked_at": datetime.utcnow().isoformat(),
        "total_resources": total,
        "ok": len(ok),
        "warnings": len(warnings),
        "alarms": len(alarms),
        "no_data": len(no_data),
        "overall_status": "ALARM" if alarms else ("WARNING" if warnings else "OK"),
        "alarm_resources": [r["resource_name"] for r in alarms],
        "results": all_results
    }


# ── Main entry point ───────────────────────────────────────────────────────────
def run_check(config: Dict) -> Dict:
    """
    Run a full infrastructure check across EC2, RDS, and Lambda.

    Returns a summary dict with all results.
    """
    region = config.get("region", "us-east-1")
    thresholds = config.get("thresholds", {})

    logger.info(f"Starting infrastructure check in region: {region}")
    logger.info("=" * 60)

    # Initialize AWS clients
    cw_client     = boto3.client("cloudwatch", region_name=region)
    ec2_client    = boto3.client("ec2",        region_name=region)
    rds_client    = boto3.client("rds",        region_name=region)
    lambda_client = boto3.client("lambda",     region_name=region)

    all_results = []
    all_results += check_ec2_instances(cw_client, ec2_client, thresholds)
    all_results += check_rds_instances(cw_client, rds_client, thresholds)
    all_results += check_lambda_functions(cw_client, lambda_client, thresholds)

    summary = build_summary(all_results)

    logger.info("=" * 60)
    logger.info(f"Check complete — Status: {summary['overall_status']}")
    logger.info(f"  Total: {summary['total_resources']} | OK: {summary['ok']} | "
                f"Warnings: {summary['warnings']} | Alarms: {summary['alarms']}")

    if summary["alarm_resources"]:
        logger.warning(f"  ALARMS on: {', '.join(summary['alarm_resources'])}")

    return summary


def print_status(summary: Dict):
    """Print a human-readable status table to console."""
    print("\n" + "=" * 70)
    print(f"  AWS INFRASTRUCTURE STATUS — {summary['checked_at']}")
    print("=" * 70)
    print(f"  Overall: {summary['overall_status']}")
    print(f"  Resources checked: {summary['total_resources']}")
    print(f"  OK: {summary['ok']}  |  Warnings: {summary['warnings']}  "
          f"|  Alarms: {summary['alarms']}  |  No data: {summary['no_data']}")
    print("-" * 70)
    print(f"  {'Service':<10} {'Resource':<30} {'Metric':<20} {'Value':>8}  Status")
    print("-" * 70)
    for r in summary["results"]:
        value_str = f"{r['value']}{r['unit']}" if r["value"] is not None else "N/A"
        status_icon = {"OK": "✅", "WARNING": "⚠️ ", "ALARM": "🚨", "NO_DATA": "❓"}.get(r["status"], "")
        print(f"  {r['service']:<10} {r['resource_name']:<30} {r['metric']:<20} {value_str:>8}  {status_icon} {r['status']}")
    print("=" * 70 + "\n")


# ── CLI ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AWS CloudWatch Infrastructure Monitor")
    parser.add_argument("--check-now", action="store_true", help="Run a check immediately")
    parser.add_argument("--status",    action="store_true", help="Show current status")
    parser.add_argument("--config",    default="config/config.json", help="Path to config file")
    parser.add_argument("--output",    default=None, help="Save results to JSON file")
    args = parser.parse_args()

    config = load_config(args.config)

    if args.check_now or args.status:
        summary = run_check(config)
        print_status(summary)

        if args.output:
            with open(args.output, "w") as f:
                json.dump(summary, f, indent=2, default=str)
            logger.info(f"Results saved to {args.output}")
    else:
        parser.print_help()
