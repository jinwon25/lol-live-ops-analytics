FROM apache/airflow:3.4.0-python3.11

# 기존 정규화 모듈의 기본 디렉터리 생성이 비루트 사용자에서도 가능해야 한다.
USER root
RUN mkdir -p /opt/project/data/processed && chown -R airflow:root /opt/project/data
USER airflow

COPY --chown=airflow:root pipeline/requirements.txt /opt/project/pipeline/requirements.txt
# 공식 이미지는 해당 릴리스의 constraints로 구성된다. 사용자 의존성 추가 시에는
# Airflow 버전을 고정하되 전체 providers용 constraints와 pandas/DuckDB를 강제로 맞추지 않는다.
RUN pip install --no-cache-dir "apache-airflow==3.4.0" \
    -r /opt/project/pipeline/requirements.txt && pip check

COPY --chown=airflow:root pipeline /opt/project/pipeline
COPY --chown=airflow:root src/__init__.py src/load.py /opt/project/src/
COPY --chown=airflow:root sql/pipeline /opt/project/sql/pipeline
COPY --chown=airflow:root orchestration/airflow/dags /opt/project/orchestration/airflow/dags

ENV PYTHONPATH=/opt/project
ENV AIRFLOW__CORE__DAGS_FOLDER=/opt/project/orchestration/airflow/dags
ENV AIRFLOW__CORE__LOAD_EXAMPLES=False
