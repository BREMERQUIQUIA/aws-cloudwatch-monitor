"""
reporter.py
===========
Generates a professional HTML health report from monitoring results
and sends it via AWS SNS email subscription.

Author: Bremer Quiquia Cirineo
GitHub: https://github.com/BREMERQUIQUIA
"""

import boto3
import json
import logging
import argparse
import os
from datetime import datetime
from typing import Dict, List
from monitor import load_config, run_check

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)


# ── HTML template ──────────────────────────────────────────────────────────────
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>AWS Infrastructure Report — {date}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f0f4f8; color: #2d3748; }}
    .header {{ background: linear-gradient(135deg, #1a202c 0%, #2d3748 100%); color: white; padding: 32px 40px; }}
    .header h1 {{ font-size: 24px; font-weight: 700; letter-spacing: -0.5px; }}
    .header p  {{ font-size: 13px; color: #a0aec0; margin-top: 6px; }}
    .container {{ max-width: 900px; margin: 0 auto; padding: 32px 20px; }}
    .summary-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 32px; }}
    .card {{ background: white; border-radius: 10px; padding: 20px; text-align: center;
             box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
    .card .value {{ font-size: 36px; font-weight: 800; line-height: 1; }}
    .card .label {{ font-size: 12px; color: #718096; margin-top: 6px; text-transform: uppercase; letter-spacing: .5px; }}
    .ok      {{ color: #38a169; }}
    .warning {{ color: #d69e2e; }}
    .alarm   {{ color: #e53e3e; }}
    .nodata  {{ color: #718096; }}
    .badge {{ display: inline-block; padding: 3px 10px; border-radius: 99px; font-size: 11px; font-weight: 700; }}
    .badge-ok      {{ background: #c6f6d5; color: #276749; }}
    .badge-warning {{ background: #fefcbf; color: #744210; }}
    .badge-alarm   {{ background: #fed7d7; color: #822727; }}
    .badge-nodata  {{ background: #e2e8f0; color: #4a5568; }}
    .section {{ background: white; border-radius: 10px; padding: 24px; margin-bottom: 24px;
                box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
    .section h2 {{ font-size: 16px; font-weight: 700; margin-bottom: 16px;
                   padding-bottom: 10px; border-bottom: 2px solid #e2e8f0; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th {{ background: #f7fafc; text-align: left; padding: 10px 12px; font-weight: 600;
          color: #4a5568; border-bottom: 2px solid #e2e8f0; }}
    td {{ padding: 10px 12px; border-bottom: 1px solid #edf2f7; vertical-align: middle; }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: #f7fafc; }}
    .footer {{ text-align: center; font-size: 12px; color: #a0aec0; padding: 20px; }}
    .overall-ok    {{ border-left: 5px solid #38a169; }}
    .overall-warn  {{ border-left: 5px solid #d69e2e; }}
    .overall-alarm {{ border-left: 5px solid #e53e3e; }}
  </style>
</head>
<body>
  <div class="header">
    <h1>☁️ AWS Infrastructure Health Report</h1>
    <p>Generated: {datetime} UTC &nbsp;|&nbsp; Region: {region} &nbsp;|&nbsp; By: aws-cloudwatch-monitor</p>
  </div>
  <div class="container">

    <!-- Summary cards -->
    <div class="summary-grid">
      <div class="card"><div class="value">{total}</div><div class="label">Resources</div></div>
      <div class="card"><div class="value ok">{ok}</div><div class="label">Healthy</div></div>
      <div class="card"><div class="value warning">{warnings}</div><div class="label">Warnings</div></div>
      <div class="card"><div class="value alarm">{alarms}</div><div class="label">Alarms</div></div>
    </div>

    <!-- Results table -->
    <div class="section {overall_class}">
      <h2>📋 Resource Status</h2>
      <table>
        <thead>
          <tr>
            <th>Service</th>
            <th>Resource</th>
            <th>Metric</th>
            <th>Value</th>
            <th>Threshold</th>
            <th>Status</th>
            <th>Checked At</th>
          </tr>
        </thead>
        <tbody>
          {rows}
        </tbody>
      </table>
    </div>

    <!-- Alarms section -->
    {alarm_section}

  </div>
  <div class="footer">
    aws-cloudwatch-monitor &nbsp;|&nbsp; github.com/BREMERQUIQUIA &nbsp;|&nbsp;
    Bremer Quiquia Cirineo &nbsp;|&nbsp; Cloud Engineer
  </div>
</body>
</html>
"""

ALARM_SECTION_TEMPLATE = """
<div class="section overall-alarm">
  <h2>🚨 Active Alarms ({count})</h2>
  <table>
    <thead><tr><th>Resource</th><th>Service</th><th>Metric</th><th>Value</th><th>Threshold</th></tr></thead>
    <tbody>{alarm_rows}</tbody>
  </table>
</div>
"""

ROW_TEMPLATE = """
<tr>
  <td><strong>{service}</strong></td>
  <td>{resource_name}</td>
  <td>{metric}</td>
  <td><strong>{value}</strong></td>
  <td>{threshold}{unit}</td>
  <td><span class="badge badge-{badge_class}">{status}</span></td>
  <td style="color:#a0aec0;font-size:11px">{checked_at}</td>
</tr>
"""


# ── HTML builder ───────────────────────────────────────────────────────────────
def build_html_report(summary: Dict, region: str) -> str:
    """Generate a full HTML report string from a monitoring summary."""

    rows = ""
    for r in summary["results"]:
        value_str = f"{r['value']}{r['unit']}" if r["value"] is not None else "N/A"
        badge_map = {"OK": "ok", "WARNING": "warning", "ALARM": "alarm", "NO_DATA": "nodata"}
        rows += ROW_TEMPLATE.format(
            service=r["service"],
            resource_name=r["resource_name"],
            metric=r["metric"],
            value=value_str,
            threshold=r["threshold"],
            unit=r["unit"],
            badge_class=badge_map.get(r["status"], "nodata"),
            status=r["status"],
            checked_at=r["checked_at"][:19].replace("T", " ")
        )

    # Alarms section
    alarm_section = ""
    alarms = [r for r in summary["results"] if r["status"] == "ALARM"]
    if alarms:
        alarm_rows = ""
        for r in alarms:
            value_str = f"{r['value']}{r['unit']}" if r["value"] is not None else "N/A"
            alarm_rows += f"<tr><td>{r['resource_name']}</td><td>{r['service']}</td>" \
                          f"<td>{r['metric']}</td><td><strong>{value_str}</strong></td>" \
                          f"<td>{r['threshold']}{r['unit']}</td></tr>"
        alarm_section = ALARM_SECTION_TEMPLATE.format(
            count=len(alarms),
            alarm_rows=alarm_rows
        )

    overall_class_map = {"OK": "overall-ok", "WARNING": "overall-warn", "ALARM": "overall-alarm"}
    now = datetime.utcnow()

    return HTML_TEMPLATE.format(
        date=now.strftime("%Y-%m-%d"),
        datetime=now.strftime("%Y-%m-%d %H:%M:%S"),
        region=region,
        total=summary["total_resources"],
        ok=summary["ok"],
        warnings=summary["warnings"],
        alarms=summary["alarms"],
        overall_class=overall_class_map.get(summary["overall_status"], "overall-ok"),
        rows=rows,
        alarm_section=alarm_section
    )


# ── S3 upload ──────────────────────────────────────────────────────────────────
def save_report_to_s3(html: str, bucket: str, region: str) -> str:
    """
    Upload HTML report to S3 and return the object URL.

    Bucket should have a lifecycle policy for cost management.
    """
    s3 = boto3.client("s3", region_name=region)
    key = f"reports/{datetime.utcnow().strftime('%Y/%m/%d')}/report.html"

    try:
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=html.encode("utf-8"),
            ContentType="text/html"
        )
        url = f"https://{bucket}.s3.{region}.amazonaws.com/{key}"
        logger.info(f"Report uploaded to S3: {url}")
        return url
    except Exception as e:
        logger.error(f"Failed to upload to S3: {e}")
        return ""


# ── SNS email ──────────────────────────────────────────────────────────────────
def send_email_via_sns(subject: str, body: str, topic_arn: str, region: str):
    """Send notification via SNS (plain text summary + link to full HTML report)."""
    sns = boto3.client("sns", region_name=region)
    try:
        sns.publish(TopicArn=topic_arn, Subject=subject, Message=body)
        logger.info(f"Email sent via SNS topic: {topic_arn}")
    except Exception as e:
        logger.error(f"Failed to send SNS notification: {e}")


# ── Main ───────────────────────────────────────────────────────────────────────
def generate_and_send(config: Dict, send_email: bool = False, save_local: bool = True):
    """Run checks, build HTML report, optionally save to S3 and send email."""

    region = config.get("region", "us-east-1")
    summary = run_check(config)
    html = build_html_report(summary, region)

    # Save locally
    if save_local:
        os.makedirs("reports", exist_ok=True)
        filename = f"reports/report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.html"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info(f"Report saved locally: {filename}")

    # Upload to S3
    report_url = ""
    s3_bucket = config.get("s3_report_bucket", "")
    if s3_bucket:
        report_url = save_report_to_s3(html, s3_bucket, region)

    # Send email via SNS
    if send_email:
        topic_arn = config.get("sns_topic_arn", "")
        if not topic_arn:
            logger.warning("sns_topic_arn not set in config — skipping email.")
        else:
            status = summary["overall_status"]
            subject = f"[{status}] AWS Infrastructure Report — {datetime.utcnow().strftime('%Y-%m-%d')}"
            body = (
                f"Infrastructure Health Report\n"
                f"{'=' * 40}\n"
                f"Status:    {status}\n"
                f"Resources: {summary['total_resources']}\n"
                f"OK:        {summary['ok']}\n"
                f"Warnings:  {summary['warnings']}\n"
                f"Alarms:    {summary['alarms']}\n"
            )
            if summary["alarm_resources"]:
                body += f"\nAlarms on: {', '.join(summary['alarm_resources'])}\n"
            if report_url:
                body += f"\nFull report: {report_url}\n"
            send_email_via_sns(subject, body, topic_arn, region)

    return summary, html


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AWS Infrastructure HTML Reporter")
    parser.add_argument("--generate",   action="store_true", help="Generate HTML report")
    parser.add_argument("--send-email", action="store_true", help="Send report via SNS email")
    parser.add_argument("--no-local",   action="store_true", help="Skip saving report locally")
    parser.add_argument("--config",     default="config/config.json", help="Path to config file")
    args = parser.parse_args()

    config = load_config(args.config)

    if args.generate:
        generate_and_send(
            config,
            send_email=args.send_email,
            save_local=not args.no_local
        )
    else:
        parser.print_help()
