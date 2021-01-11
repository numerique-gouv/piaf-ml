import logging

from tqdm import tqdm

from haystack.document_store.base import BaseDocumentStore
from haystack.retriever.base import BaseRetriever

logger = logging.getLogger(__name__)


def eval_retriever(
    document_store: BaseDocumentStore,
    retriever: BaseRetriever,
    label_index: str = "label",
    doc_index: str = "eval_document",
    label_origin: str = "gold_label",
    top_k: int = 10,
    open_domain: bool = False,
    return_preds: bool = False,
) -> dict:
    """
    Performs evaluation on the Retriever passed as parameter.
    Retriever is evaluated based on whether it finds the correct document given the query string and at which
    position in the ranking of documents the correct document is.

    |  Returns a dict containing the following metrics:

        - "recall": Proportion of questions for which correct document is among retrieved documents
        - "mrr": Mean of reciprocal rank. Rewards retrievers that give relevant documents a higher rank.
          Only considers the highest ranked relevant document.
        - "map": Mean of average precision for each question. Rewards retrievers that give relevant
          documents a higher rank. Considers all retrieved relevant documents. If ``open_domain=True``,
          average precision is normalized by the number of retrieved relevant documents per query.
          If ``open_domain=False``, average precision is normalized by the number of all relevant documents
          per query.

    :param label_origin:
    :param retriever:
    :param document_store:
    :param label_index: Index/Table in DocumentStore where labeled questions are stored
    :param doc_index: Index/Table in DocumentStore where documents that are used for evaluation are stored
    :param top_k: How many documents to return per query
    :param open_domain: If ``True``, retrieval will be evaluated by checking if the answer string to a question is
                        contained in the retrieved docs (common approach in open-domain QA).
                        If ``False``, retrieval uses a stricter evaluation that checks if the retrieved document ids
                        are within ids explicitly stated in the labels.
    :param return_preds: Whether to add predictions in the returned dictionary. If True, the returned dictionary
                         contains the keys "predictions" and "metrics".
    """

    # Extract all questions for evaluation
    filters = {"origin": [label_origin]}

    timed_retrieve = retriever.timing(retriever.retrieve)

    labels = document_store.get_all_labels_aggregated(index=label_index, filters=filters)

    correct_retrievals = 0
    summed_avg_precision = 0.0
    summed_reciprocal_rank = 0.0

    # Collect questions and corresponding answers/document_ids in a dict
    question_label_dict = {}
    for label in labels:
        if open_domain:
            question_label_dict[label.question] = label.multiple_answers
        else:
            deduplicated_doc_ids = list(set([str(x) for x in label.multiple_document_ids]))
            question_label_dict[label.question] = deduplicated_doc_ids

    predictions = []

    # Option 1: Open-domain evaluation by checking if the answer string is in the retrieved docs
    logger.info("Performing eval queries...")
    if open_domain:
        for question, gold_answers in tqdm(question_label_dict.items()):
            retrieved_docs = timed_retrieve(question, top_k=top_k, index=doc_index)
            if return_preds:
                predictions.append({"question": question, "retrieved_docs": retrieved_docs})
            # check if correct doc in retrieved docs
            found_relevant_doc = False
            relevant_docs_found = 0
            current_avg_precision = 0.0
            for doc_idx, doc in enumerate(retrieved_docs):
                for gold_answer in gold_answers:
                    if gold_answer in doc.text:
                        relevant_docs_found += 1
                        if not found_relevant_doc:
                            correct_retrievals += 1
                            summed_reciprocal_rank += 1 / (doc_idx + 1)
                        current_avg_precision += relevant_docs_found / (doc_idx + 1)
                        found_relevant_doc = True
                        break
            if found_relevant_doc:
                summed_avg_precision += current_avg_precision / relevant_docs_found
    # Option 2: Strict evaluation by document ids that are listed in the labels
    else:
        for question, gold_ids in tqdm(question_label_dict.items()):
            retrieved_docs = timed_retrieve(question, top_k=top_k, index=doc_index)
            if return_preds:
                predictions.append({"question": question, "retrieved_docs": retrieved_docs})
            # check if correct doc in retrieved docs
            found_relevant_doc = False
            relevant_docs_found = 0
            current_avg_precision = 0.0
            for doc_idx, doc in enumerate(retrieved_docs):
                for gold_id in gold_ids:
                    if str(doc.id) == gold_id:
                        relevant_docs_found += 1
                        if not found_relevant_doc:
                            correct_retrievals += 1
                            summed_reciprocal_rank += 1 / (doc_idx + 1)
                        current_avg_precision += relevant_docs_found / (doc_idx + 1)
                        found_relevant_doc = True
                        break
            if found_relevant_doc:
                all_relevant_docs = len(set(gold_ids))
                summed_avg_precision += current_avg_precision / all_relevant_docs
    # Metrics
    number_of_questions = len(question_label_dict)
    recall = correct_retrievals / number_of_questions
    mean_reciprocal_rank = summed_reciprocal_rank / number_of_questions
    mean_avg_precision = summed_avg_precision / number_of_questions

    logger.info((f"For {correct_retrievals} out of {number_of_questions} questions ({recall:.2%}), the answer was in"
                 f" the top-{top_k} candidate passages selected by the retriever."))

    metrics =  {
        "recall": recall,
        "map": mean_avg_precision,
        "mrr": mean_reciprocal_rank,
        "retrieve_time": retriever.retrieve_time,
        "n_questions": number_of_questions,
        "top_k": top_k
    }

    if return_preds:
        return {"metrics": metrics, "predictions": predictions}
    else:
        return metrics