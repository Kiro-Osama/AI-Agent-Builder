"""
Worker — Celery async task processor.

Tasks:
    build_agent.run_build_pipeline    Main pipeline task (runs LangGraph)
    sandbox_validator.validate_skill  Test a skill in Docker sandbox
"""
