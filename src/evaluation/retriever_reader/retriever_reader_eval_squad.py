import hashlib
import logging
import torch

from pathlib import Path
from tqdm import tqdm

from haystack.document_store.elasticsearch import ElasticsearchDocumentStore
from haystack.retriever.sparse import ElasticsearchRetriever
from haystack.retriever.dense import EmbeddingRetriever
from haystack.reader.transformers import TransformersReader
from haystack.pipeline import Pipeline

from farm.utils import initialize_device_settings
from sklearn.model_selection import ParameterGrid

from src.evaluation.config.retriever_reader_eval_squad_config import parameters
from src.evaluation.utils.elasticsearch_management import launch_ES, prepare_mapping
from src.evaluation.utils.preprocess import add_eval_data_from_file
from src.evaluation.utils.utils_eval import eval_retriever_reader
from src.evaluation.config.elasticsearch_mappings import SQUAD_MAPPING

GPU_AVAILABLE = torch.cuda.is_available()

if GPU_AVAILABLE:
    n_gpu = torch.cuda.current_device()
else:
    n_gpu = -1

def single_run(parameters):
    """
    Queries ES max_k - min_k times, saving at each step the results in a list. At the end plots the line
    showing the results obtained. For now we can only vary k.
    :param min_k: Minimum retriever-k to test
    :param max_k: Maximum retriever-k to test
    :param weighted_precision: Whether to take into account the position of the retrieved result in the accuracy computation
    :return:
    """
    # col names
    evaluation_data = Path(parameters["squad_dataset"])
    retriever_type = parameters["retriever_type"]
    k_retriever = parameters["k_retriever"]
    k_reader = parameters["k_reader"]
    preprocessing = parameters["preprocessing"]
    experiment_id = hashlib.md5(str(parameters).encode("utf-8")).hexdigest()[:4]
    # Prepare framework

    prepare_mapping(SQUAD_MAPPING, preprocessing)

    # Connect to Elasticsearch
    document_store = ElasticsearchDocumentStore(host="localhost", username="", password="", index="document",
                                                create_index=False, embedding_field="emb",
                                                embedding_dim=512, excluded_meta_data=["emb"], similarity='cosine',
                                                custom_mapping=SQUAD_MAPPING)

    # Initialize Retriever
    retriever_bm25 = ElasticsearchRetriever(document_store=document_store)
    retriever_emb = EmbeddingRetriever(document_store=document_store,
                                       embedding_model="distiluse-base-multilingual-cased",
                                       use_gpu=GPU_AVAILABLE, model_format="sentence_transformers",
                                       pooling_strategy="reduce_max",
                                       emb_extraction_layer=-2)

    reader = TransformersReader(model_name_or_path="etalab-ia/camembert-base-squadFR-fquad-piaf",
                                tokenizer="etalab-ia/camembert-base-squadFR-fquad-piaf",
                                use_gpu=n_gpu,top_k_per_candidate=k_reader)

    p = Pipeline()

    if retriever_type == 'bm25':
        retriever = retriever_bm25
        p.add_node(component=retriever, name="Retriever", inputs=["Query"])
    elif retriever_type == "sbert":
        retriever = retriever_emb
        p.add_node(component=retriever, name="Retriever", inputs=["Query"])
    else:
        raise Exception(f"You chose {retriever_type}. Choose one from bm25, sbert, or dpr")

    p.add_node(component=reader, name='reader', inputs=['Retriever'])

    # Add evaluation data to Elasticsearch document store
    # We first delete the custom tutorial indices to not have duplicate elements
    # make sure these indices do not collide with existing ones, the indices will be wiped clean before data is inserted
    doc_index = "document"
    label_index = "label"

    document_store.delete_all_documents(index=doc_index)
    document_store.delete_all_documents(index=label_index)
    document_store.add_eval_data(evaluation_data.as_posix(), doc_index=doc_index, label_index=label_index)
    document_store.update_embeddings(retriever_emb, index=doc_index)

    retriever_eval_results = eval_retriever_reader(document_store=document_store, pipeline=p, top_k_reader=k_reader,
                                                   top_k_retriever=k_retriever, label_index=label_index,
                                                   doc_index=doc_index)

    print("Reader Accuracy:", retriever_eval_results["reader_topk_accuracy"])
    print("reader_topk_f1:", retriever_eval_results["reader_topk_f1"])

    return retriever_eval_results


if __name__ == '__main__':
    result_file_path = Path("./results/results.csv")
    parameters_grid = list(ParameterGrid(param_grid=parameters))

    device, n_gpu = initialize_device_settings(use_cuda=False)

    logger = logging.getLogger(__name__)

    all_results = []
    launch_ES()
    for param in tqdm(parameters_grid, desc="GridSearch"):
        # START XP
        run_results = single_run(param)
        print(run_results)
        all_results.append(run_results)

    #save_results(result_file_path=result_file_path, all_results=all_results)
    print(all_results)