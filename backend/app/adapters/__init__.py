"""Source adapter contracts and concrete provider implementations (#259)."""

from app.adapters.contracts import (
    AdapterContractError,
    AdapterParseError,
    AdapterSchemaError,
    CanonicalTransaction,
    ReceiptAdapterResult,
    ReceiptSourceAdapter,
    SourceProvenanceSpec,
    TransactionAdapterResult,
    TransactionBatchAdapterResult,
    TransactionSourceAdapter,
    degrade_quality,
)
from app.adapters.receipt_adapters import (
    EParagonReceiptAdapter,
    LidlMappingSchemaError,
    LidlPlusReceiptAdapter,
    OcrPipelineReceiptAdapter,
)
from app.adapters.transaction_adapters import (
    IngCsvTransactionAdapter,
    IngPdfTransactionAdapter,
    parse_ing_pdf_text,
)

__all__ = [
    "AdapterContractError",
    "AdapterParseError",
    "AdapterSchemaError",
    "CanonicalTransaction",
    "EParagonReceiptAdapter",
    "IngCsvTransactionAdapter",
    "IngPdfTransactionAdapter",
    "LidlMappingSchemaError",
    "LidlPlusReceiptAdapter",
    "OcrPipelineReceiptAdapter",
    "ReceiptAdapterResult",
    "ReceiptSourceAdapter",
    "SourceProvenanceSpec",
    "TransactionAdapterResult",
    "TransactionBatchAdapterResult",
    "TransactionSourceAdapter",
    "degrade_quality",
    "parse_ing_pdf_text",
]
