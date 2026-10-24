"""Testes de concorrência, paralelismo e prevenção de estoque negativo."""

from __future__ import annotations

import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib import inventory, orders
from lib.database import connection, init_database, transaction
from lib.errors import DomainError


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Garante um banco isolado para cada teste de concorrência."""
    db_path = tmp_path / "sg_concurrency_test.db"
    monkeypatch.setenv("SG_DB_PATH", str(db_path))
    init_database(seed_demo=True)
    yield db_path


def _create_test_product(initial_stock: int, sku: str = "CONC-PROD-01") -> int:
    """Cria um produto isolado com estoque inicial controlado."""
    now = "2026-01-01 10:00:00"
    with transaction() as conn:
        cursor = conn.execute(
            """
            INSERT INTO products (sku, name, category, description, price, cost, stock, min_stock, active, created_at, updated_at)
            VALUES (?, ?, 'Eletrônicos', 'Produto teste concorrência', 100.0, 50.0, ?, 0, 1, ?, ?)
            """,
            (sku, f"Produto {sku}", initial_stock, now, now),
        )
        return int(cursor.lastrowid)


def _get_customer_id() -> int:
    with connection() as conn:
        row = conn.execute("SELECT id FROM customers LIMIT 1").fetchone()
        return int(row["id"])


def test_concurrent_manual_stock_out_prevents_negative_stock():
    """Testa múltiplas saídas manuais concorrentes em paralelo.
    
    Cenário:
    - Estoque inicial: 5 unidades
    - 15 threads tentam dar baixa simultânea de 1 unidade cada
    - Deve resultar em exatamente 5 sucessos e 10 falhas por falta de estoque
    - O estoque final deve ser rigorosamente 0 (nunca negativo)
    """
    initial_stock = 5
    num_threads = 15
    product_id = _create_test_product(initial_stock, sku="CONC-OUT-01")

    barrier = threading.Barrier(num_threads)
    results: list[dict] = []
    results_lock = threading.Lock()

    def worker(worker_id: int):
        # Sincroniza todas as threads para dispararem exatamente no mesmo instante
        barrier.wait()
        try:
            doc_id = inventory.create_stock_document(
                kind="Saída",
                items=[{"product_id": product_id, "quantity": 1}],
                reason=f"Baixa concorrente worker {worker_id}",
                actor=f"Worker-{worker_id}",
                status="Concluído",
            )
            with results_lock:
                results.append({"status": "SUCCESS", "doc_id": doc_id})
        except DomainError as err:
            with results_lock:
                results.append({"status": "DOMAIN_ERROR", "error": str(err)})
        except Exception as exc:
            with results_lock:
                results.append({"status": "UNEXPECTED_ERROR", "error": f"{type(exc).__name__}: {exc}"})

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker, i) for i in range(num_threads)]
        for f in futures:
            f.result()

    successes = [r for r in results if r["status"] == "SUCCESS"]
    domain_errors = [r for r in results if r["status"] == "DOMAIN_ERROR"]
    unexpected = [r for r in results if r["status"] == "UNEXPECTED_ERROR"]

    # Nenhuma exceção inesperada (ex: IntegrityError, database locked não tratado)
    assert not unexpected, f"Erros inesperados ocorreram: {unexpected}"

    # Exatamente 5 sucessos e 10 recusas controladas
    assert len(successes) == initial_stock
    assert len(domain_errors) == num_threads - initial_stock

    for err in domain_errors:
        assert "Estoque insuficiente" in err["error"]

    # Validação do estado no banco de dados
    with connection() as conn:
        row = conn.execute("SELECT stock FROM products WHERE id = ?", (product_id,)).fetchone()
        assert row["stock"] == 0

        # Verifica histórico de movimentações geradas
        movements = conn.execute(
            "SELECT quantity, balance_before, balance_after FROM stock_movements WHERE product_id = ? ORDER BY id",
            (product_id,),
        ).fetchall()
        assert len(movements) == initial_stock
        for m in movements:
            assert m["quantity"] == -1
            assert m["balance_after"] >= 0
            assert m["balance_before"] > m["balance_after"]


def test_concurrent_orders_creation_prevents_negative_stock():
    """Testa criação concorrente de pedidos simultâneos consumindo estoque.
    
    Cenário:
    - Estoque inicial: 4 unidades
    - 12 threads tentam fechar pedido de 1 unidade cada no mesmo instante
    - Exatamente 4 pedidos devem ser criados e 8 devem ser rejeitados
    - O estoque final deve ser 0 (nunca negativo)
    """
    initial_stock = 4
    num_threads = 12
    product_id = _create_test_product(initial_stock, sku="CONC-ORD-01")
    customer_id = _get_customer_id()

    barrier = threading.Barrier(num_threads)
    results: list[dict] = []
    results_lock = threading.Lock()

    def worker(worker_id: int):
        barrier.wait()
        try:
            order_id, number = orders.create_order(
                customer_id=customer_id,
                status="Pendente",
                payment_method="Pix",
                channel="Site",
                discount=0,
                shipping=0,
                notes=f"Pedido concorrente {worker_id}",
                items=[(product_id, 1)],
                actor=f"Worker-{worker_id}",
            )
            with results_lock:
                results.append({"status": "SUCCESS", "order_id": order_id, "number": number})
        except DomainError as err:
            with results_lock:
                results.append({"status": "DOMAIN_ERROR", "error": str(err)})
        except Exception as exc:
            with results_lock:
                results.append({"status": "UNEXPECTED_ERROR", "error": f"{type(exc).__name__}: {exc}"})

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker, i) for i in range(num_threads)]
        for f in futures:
            f.result()

    successes = [r for r in results if r["status"] == "SUCCESS"]
    domain_errors = [r for r in results if r["status"] == "DOMAIN_ERROR"]
    unexpected = [r for r in results if r["status"] == "UNEXPECTED_ERROR"]

    assert not unexpected, f"Erros inesperados: {unexpected}"
    assert len(successes) == initial_stock
    assert len(domain_errors) == num_threads - initial_stock

    with connection() as conn:
        prod = conn.execute("SELECT stock FROM products WHERE id = ?", (product_id,)).fetchone()
        assert prod["stock"] == 0

        # Total de itens vendidos deve ser exatamente 4
        total_items = conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) FROM order_items WHERE product_id = ?",
            (product_id,),
        ).fetchone()[0]
        assert total_items == initial_stock


def test_concurrent_order_reactivations_prevent_negative_stock():
    """Testa reativação concorrente de pedidos cancelados.
    
    Cenário:
    - 5 pedidos cancelados aguardando reativação (cada um precisa de 1 unidade)
    - O estoque do produto é limitado a apenas 2 unidades
    - 5 threads tentam reativar seus respectivos pedidos simultaneamente
    - Apenas 2 reativações devem ter sucesso, as outras 3 devem falhar
    - O estoque final deve ser 0 (nunca negativo)
    """
    customer_id = _get_customer_id()
    product_id = _create_test_product(initial_stock=10, sku="CONC-REACT-01")

    # Cria 5 pedidos e depois cancela todos
    order_ids = []
    for i in range(5):
        oid, _ = orders.create_order(
            customer_id=customer_id,
            status="Pendente",
            payment_method="Pix",
            channel="Site",
            discount=0,
            shipping=0,
            notes=f"Pedido base {i}",
            items=[(product_id, 1)],
            actor="Admin",
        )
        orders.update_order_status(oid, "Cancelado", actor="Admin")
        order_ids.append(oid)

    # Força estoque atual em exatamente 2 unidades
    with transaction() as conn:
        conn.execute("UPDATE products SET stock = 2 WHERE id = ?", (product_id,))

    num_threads = len(order_ids)
    barrier = threading.Barrier(num_threads)
    results: list[dict] = []
    results_lock = threading.Lock()

    def worker(order_id: int):
        barrier.wait()
        try:
            orders.update_order_status(order_id, "Pendente", actor=f"Reactivator-{order_id}")
            with results_lock:
                results.append({"status": "SUCCESS", "order_id": order_id})
        except DomainError as err:
            with results_lock:
                results.append({"status": "DOMAIN_ERROR", "error": str(err)})
        except Exception as exc:
            with results_lock:
                results.append({"status": "UNEXPECTED_ERROR", "error": f"{type(exc).__name__}: {exc}"})

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker, oid) for oid in order_ids]
        for f in futures:
            f.result()

    successes = [r for r in results if r["status"] == "SUCCESS"]
    domain_errors = [r for r in results if r["status"] == "DOMAIN_ERROR"]
    unexpected = [r for r in results if r["status"] == "UNEXPECTED_ERROR"]

    assert not unexpected, f"Erros inesperados: {unexpected}"
    assert len(successes) == 2
    assert len(domain_errors) == 3

    with connection() as conn:
        prod = conn.execute("SELECT stock FROM products WHERE id = ?", (product_id,)).fetchone()
        assert prod["stock"] == 0


def test_concurrent_transfers_prevent_negative_stock():
    """Testa transferências concorrentes em paralelo com status Concluído."""
    initial_stock = 3
    num_threads = 10
    product_id = _create_test_product(initial_stock, sku="CONC-TRF-01")
    entity_id = inventory.save_stock_entity(
        kind="Filial",
        name="Filial Concorrência",
        document=None,
        city="São Paulo",
        state="SP",
        active=True,
    )

    barrier = threading.Barrier(num_threads)
    results: list[dict] = []
    results_lock = threading.Lock()

    def worker(worker_id: int):
        barrier.wait()
        try:
            doc_id = inventory.create_stock_document(
                kind="Transferência",
                items=[{"product_id": product_id, "quantity": 1}],
                reason=f"Transferência concorrente worker {worker_id}",
                actor=f"Worker-{worker_id}",
                entity_kind="Filial",
                entity_id=entity_id,
                status="Concluído",
            )
            with results_lock:
                results.append({"status": "SUCCESS", "doc_id": doc_id})
        except DomainError as err:
            with results_lock:
                results.append({"status": "DOMAIN_ERROR", "error": str(err)})
        except Exception as exc:
            with results_lock:
                results.append({"status": "UNEXPECTED_ERROR", "error": f"{type(exc).__name__}: {exc}"})

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker, i) for i in range(num_threads)]
        for f in futures:
            f.result()

    successes = [r for r in results if r["status"] == "SUCCESS"]
    domain_errors = [r for r in results if r["status"] == "DOMAIN_ERROR"]
    unexpected = [r for r in results if r["status"] == "UNEXPECTED_ERROR"]

    assert not unexpected, f"Erros inesperados: {unexpected}"
    assert len(successes) == initial_stock
    assert len(domain_errors) == num_threads - initial_stock

    with connection() as conn:
        row = conn.execute("SELECT stock FROM products WHERE id = ?", (product_id,)).fetchone()
        assert row["stock"] == 0


def test_reverse_entrada_prevents_negative_stock():
    """Testa que estornar uma entrada quando o estoque já foi consumido é impedido."""
    product_id = _create_test_product(initial_stock=0, sku="CONC-REV-01")

    # Entrada de 10 unidades
    doc_id = inventory.create_stock_document(
        kind="Entrada",
        items=[{"product_id": product_id, "quantity": 10, "unit_cost": 20.0}],
        reason="Entrada para teste de estorno",
        actor="Admin",
        status="Concluído",
    )

    # Consome 8 unidades (restando 2 unidades)
    inventory.create_stock_document(
        kind="Saída",
        items=[{"product_id": product_id, "quantity": 8}],
        reason="Saída de consumo",
        actor="Admin",
        status="Concluído",
    )

    with connection() as conn:
        assert conn.execute("SELECT stock FROM products WHERE id = ?", (product_id,)).fetchone()["stock"] == 2

    # Tenta estornar a entrada de 10 unidades (precisaria de 10 unidades, mas só há 2)
    with pytest.raises(DomainError) as exc_info:
        inventory.reverse_stock_document(doc_id, actor="Admin")

    assert "Estoque insuficiente para estornar" in str(exc_info.value)

    # O estoque deve continuar em 2 (não pode ficar -8)
    with connection() as conn:
        assert conn.execute("SELECT stock FROM products WHERE id = ?", (product_id,)).fetchone()["stock"] == 2
