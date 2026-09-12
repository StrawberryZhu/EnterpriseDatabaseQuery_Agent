from __future__ import annotations

import json
import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.rag import HybridRetriever
from app.service import AnalysisService

def normalize(rows):
    def value(v):
        if isinstance(v, float):
            return round(v, 2)
        return v
    return [{k: value(v) for k, v in row.items()} for row in rows]


def percentile(values, p):
    if not values:
        return 0
    values = sorted(values)
    return values[min(len(values)-1, round((len(values)-1)*p))]


def run() -> dict:
    service = AnalysisService()
    cases = json.loads((ROOT / 'evals' / 'northwind_cases.json').read_text(encoding='utf-8'))
    results = []
    for case in cases:
        thread = service.repo.create_thread(title='离线评测')
        run_id = service.create_analysis(thread_id=thread.id, question=case['question'])
        for _ in range(600):
            record = service.repo.get_run(run_id)
            if record.status in {'completed','completed_with_warning','failed','canceled'}:
                break
            time.sleep(0.1)
        expected = normalize(service.source.query(case['reference_sql'])['rows'])
        actual = normalize((record.answer or {}).get('table', {}).get('rows', []))
        results.append({
            'id': case['id'], 'question': case['question'], 'status': record.status,
            'correct': actual == expected, 'first_sql_success': record.first_sql_success is True,
            'latency_ms': record.latency_ms,
        })

    retriever = HybridRetriever()
    rag_cases = json.loads((ROOT / 'evals' / 'rag_cases.json').read_text(encoding='utf-8'))
    reciprocal = []
    hits = 0
    for case in rag_cases:
        ids = [item.id for item in retriever.retrieve(case['query'], top_k=5)]
        if case['expected_id'] in ids:
            hits += 1
            reciprocal.append(1 / (ids.index(case['expected_id']) + 1))
        else:
            reciprocal.append(0)

    correct = sum(x['correct'] for x in results)
    sql_ok = sum(x['first_sql_success'] for x in results)
    latencies = [x['latency_ms'] for x in results]
    metrics = {
        'result_accuracy': round(correct / len(results) * 100, 2),
        'first_sql_success_rate': round(sql_ok / len(results) * 100, 2),
        'rag_recall_at_5': round(hits / len(rag_cases), 4),
        'rag_mrr': round(sum(reciprocal) / len(reciprocal), 4),
        'avg_latency_ms': round(sum(latencies) / len(latencies), 2),
        'p95_latency_ms': round(percentile(latencies, .95), 2),
    }
    settings = get_settings()
    dataset_name = 'Northwind Eval v1（真实Qwen）' if settings.real_llm_enabled else 'Northwind Eval v1（离线Mock基线）'
    service.repo.save_eval_run(dataset_name, settings.llm_model if settings.real_llm_enabled else 'Mock', metrics, len(results))
    report = {'dataset': dataset_name, 'case_count': len(results), 'metrics': metrics, 'cases': results}
    (ROOT / 'evals' / 'latest_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return report


if __name__ == '__main__':
    run()
