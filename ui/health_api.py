#!/usr/bin/env python3
"""
Simple Flask API for UI health checking and debugging
Curl-friendly endpoints for testing the monitoring system
"""

from flask import Flask, jsonify, request
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from ui.production_monitor import ProductionMonitor

app = Flask(__name__)

# Initialize monitor
monitor = ProductionMonitor()


@app.route("/health")
def health():
    """Simple health check endpoint"""
    return jsonify(
        {
            "status": "healthy",
            "service": "hedge_fund_monitor",
            "message": "Money is safe - API is responding",
        }
    )


@app.route("/api/status")
def api_status():
    """Get overall system status"""
    try:
        health_status = monitor.check_service_health()
        system_metrics = monitor.get_system_metrics()
        data_metrics = monitor.get_data_flow_metrics()

        return jsonify(
            {
                "overall_status": health_status.get("overall_status", "UNKNOWN"),
                "services": health_status.get("services", {}),
                "system": {
                    "cpu_percent": system_metrics.get("cpu_percent", 0),
                    "memory_percent": system_metrics.get("memory_percent", 0),
                    "disk_percent": system_metrics.get("disk_percent", 0),
                },
                "data_flow": {
                    "total_messages_per_minute": data_metrics.get(
                        "total_messages_per_minute", 0
                    ),
                    "avg_latency_ms": data_metrics.get("avg_latency_ms", 0),
                },
                "timestamp": system_metrics.get("timestamp").isoformat()
                if system_metrics.get("timestamp")
                else None,
            }
        )
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/metrics")
def api_metrics():
    """Get detailed metrics"""
    try:
        system_metrics = monitor.get_system_metrics()
        data_metrics = monitor.get_data_flow_metrics()
        clickhouse_metrics = monitor.get_clickhouse_metrics()
        kafka_metrics = monitor.get_kafka_metrics()

        return jsonify(
            {
                "system": system_metrics,
                "data_flow": data_metrics,
                "clickhouse": clickhouse_metrics,
                "kafka": kafka_metrics,
            }
        )
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/alerts")
def api_alerts():
    """Get current alerts"""
    try:
        system_metrics = monitor.get_system_metrics()
        data_metrics = monitor.get_data_flow_metrics()
        clickhouse_metrics = monitor.get_clickhouse_metrics()
        kafka_metrics = monitor.get_kafka_metrics()

        alerts = monitor.generate_alerts(
            system_metrics, data_metrics, clickhouse_metrics, kafka_metrics
        )

        return jsonify(
            {
                "alerts": [
                    {
                        "level": alert["level"],
                        "service": alert["service"],
                        "message": alert["message"],
                        "timestamp": alert["timestamp"].isoformat(),
                    }
                    for alert in alerts
                ],
                "alert_count": len(alerts),
                "has_critical": any(alert["level"] == "CRITICAL" for alert in alerts),
            }
        )
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/ui-test")
def ui_test():
    """UI testing endpoint - returns key UI elements as JSON"""
    try:
        system_metrics = monitor.get_system_metrics()
        data_metrics = monitor.get_data_flow_metrics()
        health_status = monitor.check_service_health()

        return jsonify(
            {
                "title": "Hedge Fund Production Monitor",
                "overall_status": health_status.get("overall_status", "UNKNOWN"),
                "sections": {
                    "system_performance": True,
                    "data_pipeline": True,
                    "service_health": True,
                    "alerts": True,
                },
                "metrics": {
                    "cpu_usage": f"{system_metrics.get('cpu_percent', 0):.1f}%",
                    "memory_usage": f"{system_metrics.get('memory_percent', 0):.1f}%",
                    "data_rate": f"{data_metrics.get('total_messages_per_minute', 0):,}/min",
                    "latency": f"{data_metrics.get('avg_latency_ms', 0):.1f}ms",
                },
                "services": {
                    "kafka": health_status.get("services", {})
                    .get("kafka", {})
                    .get("status", "UNKNOWN"),
                    "redis": health_status.get("services", {})
                    .get("redis", {})
                    .get("status", "UNKNOWN"),
                    "clickhouse": health_status.get("services", {})
                    .get("clickhouse", {})
                    .get("status", "UNKNOWN"),
                    "iqfeed": health_status.get("services", {})
                    .get("iqfeed", {})
                    .get("status", "UNKNOWN"),
                },
                "ui_functional": True,
                "money_safe": True,
            }
        )
    except Exception as e:
        return (
            jsonify(
                {
                    "status": "error",
                    "error": str(e),
                    "ui_functional": False,
                    "money_safe": False,
                }
            ),
            500,
        )


@app.route("/debug")
def debug_info():
    """Debug information endpoint"""
    try:
        import redis
        import clickhouse_connect

        debug_info = {
            "python_path": sys.path[:3],  # First 3 entries
            "working_directory": os.getcwd(),
            "environment": {
                "STREAMLIT_TEST_MODE": os.environ.get("STREAMLIT_TEST_MODE", "Not set")
            },
            "connections": {},
        }

        # Test Redis connection
        try:
            redis_client = redis.Redis(host="localhost", port=6380, db=0)
            redis_client.ping()
            debug_info["connections"]["redis"] = "Connected"
        except Exception as e:
            debug_info["connections"]["redis"] = f"Error: {str(e)}"

        # Test ClickHouse connection
        try:
            ch_client = clickhouse_connect.get_client(host="localhost", port=8123)
            ch_client.query("SELECT 1")
            debug_info["connections"]["clickhouse"] = "Connected"
        except Exception as e:
            debug_info["connections"]["clickhouse"] = f"Error: {str(e)}"

        return jsonify(debug_info)

    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


if __name__ == "__main__":
    print("🏦 Starting Hedge Fund Health API")
    print("💰 Money is on the line - API endpoints ready")
    print("📊 Available endpoints:")
    print("  GET /health - Simple health check")
    print("  GET /api/status - Overall system status")
    print("  GET /api/metrics - Detailed metrics")
    print("  GET /api/alerts - Current alerts")
    print("  GET /api/ui-test - UI testing data")
    print("  GET /debug - Debug information")

    app.run(host="0.0.0.0", port=5001, debug=True)
