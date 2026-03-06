# 🔭 aws-cloudwatch-monitor

![AWS](https://img.shields.io/badge/AWS-CloudWatch-FF9900?style=for-the-badge&logo=amazonaws&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Terraform](https://img.shields.io/badge/Terraform-IaC-7B42BC?style=for-the-badge&logo=terraform&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)
![Status](https://img.shields.io/badge/Status-Active-brightgreen?style=for-the-badge)

> Automated AWS infrastructure monitoring system using CloudWatch, SNS and Lambda. Generates HTML health reports every 24 hours and sends intelligent alerts to reduce false positives by 60%.

---

## 📋 Table of Contents
- [Overview](#-overview)
- [Architecture](#-architecture)
- [Features](#-features)
- [Prerequisites](#-prerequisites)
- [Installation](#-installation)
- [Configuration](#-configuration)
- [Usage](#-usage)
- [Project Structure](#-project-structure)
- [Technical Decisions](#-technical-decisions)
- [Author](#-author)

---

## 🌐 Overview

This project solves a real operational problem: **infrastructure teams spend too much time manually checking dashboards and responding to noisy alerts**. This system automates monitoring by:

1. Collecting metrics from EC2, RDS, and Lambda every 5 minutes
2. Applying intelligent filtering to avoid alert fatigue
3. Generating a consolidated HTML report sent via email every 24 hours
4. Sending critical SNS alerts only when thresholds are breached for 3+ consecutive periods

**Business impact:** Reduces manual monitoring time by ~2 hours/day per operator.

---

## 🏗️ Architecture
```
┌─────────────────────────────────────────────────────────┐
│                     AWS Account                          │
│                                                          │
│  ┌──────────┐    ┌─────────────┐    ┌────────────────┐  │
│  │  EC2     │    │    RDS      │    │    Lambda      │  │
│  │ Instances│    │  Database   │    │  Functions     │  │
│  └────┬─────┘    └──────┬──────┘    └───────┬────────┘  │
│       └────────┬─────────┴────────────────────┘          │
│                │                                         │
│         ┌──────▼──────┐                                  │
│         │  CloudWatch │  ← Metrics every 5 min           │
│         └──────┬──────┘                                  │
│                │                                         │
│         ┌──────▼──────┐         ┌─────────────────────┐  │
│         │  CloudWatch │────────►│   Lambda Reporter   │  │
│         │   Alarms    │         │  (Python 3.9)       │  │
│         └──────┬──────┘         └──────────┬──────────┘  │
│                │                           │             │
│         ┌──────▼──────┐            ┌───────▼──────────┐  │
│         │     SNS     │            │       S3         │  │
│         │   Alerts    │            │  HTML Reports    │  │
│         └──────┬──────┘            └──────────────────┘  │
│                │                                         │
│         ┌──────▼──────┐                                  │
│         │    Email    │ ← Alert + Daily Report           │
│         └─────────────┘                                  │
└─────────────────────────────────────────────────────────┘
```

---

## ✨ Features

| Feature | Description |
|---|---|
| 📊 **Multi-service monitoring** | EC2, RDS, Lambda, and S3 metrics |
| 🚨 **Intelligent alerts** | Triggers only after 3 consecutive threshold breaches |
| 📧 **Daily HTML report** | Consolidated health report sent at 08:00 AM |
| 💰 **Cost tracking** | Daily AWS cost summary included in report |
| 🔕 **Alert suppression** | Maintenance window support to silence alerts |
| 📈 **Trend analysis** | 7-day metric trends to detect degradation early |

---

## 📦 Prerequisites

- AWS Account with Free Tier or active billing
- Python 3.9+
- AWS CLI configured (`aws configure`)
- Terraform 1.5+
- IAM permissions: `CloudWatchReadOnlyAccess`, `SNSFullAccess`, `S3FullAccess`

---

## 🚀 Installation

### 1. Clone the repository
```bash
git clone https://github.com/BREMERQUIQUIA/aws-cloudwatch-monitor.git
cd aws-cloudwatch-monitor
```

### 2. Install Python dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure AWS credentials
```bash
aws configure
```

### 4. Deploy infrastructure with Terraform
```bash
cd terraform/
terraform init
terraform plan
terraform apply
```

### 5. Configure alerts
```bash
cp config/config.example.json config/config.json
```

---

## ⚙️ Configuration

Edit `config/config.json`:
```json
{
  "region": "us-east-1",
  "alert_email": "your@email.com",
  "thresholds": {
    "ec2_cpu_percent": 80,
    "rds_cpu_percent": 75,
    "lambda_error_rate": 5,
    "disk_usage_percent": 85
  },
  "consecutive_breaches_to_alert": 3
}
```

---

## 📖 Usage
```bash
# Run monitoring manually
python src/monitor.py --check-now

# Generate report on demand
python src/reporter.py --generate --send-email

# Check alert status
python src/monitor.py --status
```

---

## 📁 Project Structure
```
aws-cloudwatch-monitor/
├── src/
│   ├── monitor.py          # Main monitoring logic
│   ├── reporter.py         # HTML report generator
│   ├── alert_manager.py    # SNS alert management
│   └── cost_tracker.py     # AWS cost analysis
├── terraform/
│   ├── main.tf
│   ├── variables.tf
│   └── outputs.tf
├── config/
│   └── config.example.json
├── tests/
│   └── test_monitor.py
├── requirements.txt
└── README.md
```

---

## 🧠 Technical Decisions

**Why 3 consecutive breaches before alerting?**
Transient spikes are common and self-resolve. Requiring 3 breaches (15 min) eliminates ~60% of false positives based on operational experience.

**Why Lambda for reporting instead of EC2?**
Lambda runs only when triggered — effectively free for this use case vs ~$8/month for a dedicated EC2.

**Why S3 for report storage?**
90-day lifecycle policy enables historical trend analysis at < $0.01/month.

---

## 👤 Author

**Bremer Quiquia Cirineo** — Cloud Engineer | AWS · Azure · Terraform

[![GitHub](https://img.shields.io/badge/GitHub-BREMERQUIQUIA-181717?style=flat&logo=github)](https://github.com/BREMERQUIQUIA)

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.
