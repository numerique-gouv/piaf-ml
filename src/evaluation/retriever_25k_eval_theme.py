"""
Evaluates the Retriever with different input parameters

Usage:
    retriever_perf_eval_25k.py <test_corpus_path> <knowledge_base_path> <result_file_path> <retriever_type> [options]

Arguments:
    <test_corpus_path>             The path of a 25k dataset corpus file (the 25k QA from la DILA)
    <knowledge_base_path>          The path of a knowledge-base corpus folder (the SPF uni/multi-fiches)
    <result_file_path>             The path of a results file where to store the run's perf results
    <retriever_type>               Type of retriever to use (sparse (bm25 as usual) or dense (embeddings, SBERT))
    <filtered>
    --cores=<n> CORES       Number of cores to use [default: 1:int]
"""

import json
import logging
import subprocess
import time
from pathlib import Path
from random import seed
from typing import Dict, List

from argopt import argopt
from haystack.retriever.base import BaseRetriever

from src.util.convert_json_files_to_dicts import convert_json_files_v10_to_dicts

seed(42)
from tqdm import tqdm
from haystack.document_store.elasticsearch import ElasticsearchDocumentStore
from haystack.retriever.sparse import ElasticsearchRetriever
from haystack.retriever.dense import EmbeddingRetriever

import pandas as pd

logger = logging.getLogger(__name__)


# CONFIG
# TEST_CORPUS_PATH = "./data/25k_data/15082020-ServicePublic_QR_20170612_20180612_464_single_questions.csv"
# MODEL_TOKENIZER = "etalab-ia/camembert-base-squadFR-fquad-piaf"
# RETRIEVER = "sparse"  # sparse = bm25 ; dense = embeddings

def load_25k_test_set(corpus_path: str):
    """
    Loads the 25k dataset. The 25k dataset is a csv that must contain the url columns (url, url2, url3, url4)
    and a question column. The former contains the list of proposed fiches' URLs and the latter contains the
    question sent by an user.
    :param corpus_path: Path of the file containing the 25k corpus
    :return: Dict with the questions as key and a meta dict as values,
    the meta dict containing urls where the answer is and the arborescence of where the answer lies
    """
    url_cols = ["url", "url_2", "url_3", "url_4"]

    df = pd.read_csv(corpus_path).fillna("")
    dict_question_fiche = {}
    for row in df.iterrows():
        question = row[1]["question"]
        list_url = [row[1][u] for u in url_cols if row[1][u]]
        arbo = {'theme': row[1]['theme'],
                'dossier': row[1]['dossier']}
        meta = {'urls': list_url, 'arbo': arbo}
        dict_question_fiche[question] = meta

    return dict_question_fiche


def compute_retriever_precision(true_fiches, retrieved_fiches, weight_position):
    """
    Computes an accuracy-like score to determine the fairness of the retriever.
    Takes the k *retrieved* fiches' names and counts how many of them exist in the *true* fiches names

    :param retrieved_fiches:
    :param true_fiches:
    :param weight_position: Bool indicates if the precision must be calculated with a weighted precision
    :return:
    """
    summed_precision = 0
    for fiche_idx, true_fiche_id in enumerate(true_fiches):
        for retrieved_doc_idx, doc in enumerate(retrieved_fiches):
            if true_fiche_id in doc:
                if weight_position:
                    summed_precision += ((fiche_idx + 1) / (fiche_idx + retrieved_doc_idx + 1))
                else:
                    summed_precision += 1
                break
    return summed_precision


# compute_retriever_precision(["f1", "f2", "f3"], ["f3"], False)

def main(test_corpus_path: str, knowledge_base_path: str, result_file_path: str, retriever_type: str, filter_level: str,
         k_value: int = 1, weight_position: bool = True):

    def eval_plot_k(k: int, weight_position: bool):
        """
        Queries ES max_k - min_k times, saving at each step the results in a list. At the end plots the line
        showing the results obtained. For now we can only vary k.
        :param k: Number of retriever-k to test
        :param weight_position: Whether to take into account the position of the retrieved result in the accuracy computation
        :return:
        """
        corpus_name = knowledge_base_path.split('/')[-2]
        tqdm.write(f"Testing k={k}")
        mean_precision, avg_time, correctly_retrieved, detailed_results_weighted, nb_questions = compute_score(retriever=retriever,
                                                                                                 retriever_top_k=k,
                                                                                                 test_dataset=test_dataset,
                                                                                                 weight_position=weight_position,
                                                                                                 filter_level=filter_level)
        result_dict = {"k": k,
                       "corpus": corpus_name,
                       "retriever": retriever_type,
                       "filter_level": filter_level,
                       "nb_documents": nb_questions,
                       "correctly_retrieved": correctly_retrieved,
                       "weighted_precision": str(weight_position),
                       "precision": mean_precision,
                       "avg_time_s": avg_time}
        return result_dict

    def single_run(retriever_top_k: int):
        """
        Runs the Retriever once with the specified retriever k.
        :param retriever_top_k:
        :return:
        """
        mean_precision, avg_time, found_fiche, detailed_results, nb_questions = compute_score(retriever=retriever,
                                                                                retriever_top_k=retriever_top_k,
                                                                                test_dataset=test_dataset,
                                                                                weight_position=True)
        with open(f"./results/k_{retriever_top_k}_detailed_results.json", "w") as outo:
            json.dump(detailed_results, outo, indent=4, ensure_ascii=False)

    retriever = prepare_framework(knowledge_base_path=knowledge_base_path, retriever_type=retriever_type)
    if not retriever:
        logger.info("Could not prepare the testing framework!! Exiting :(")
        return

    results = []

    test_dataset = load_25k_test_set(test_corpus_path)
    result_dict = eval_plot_k(k_value, weight_position=weight_position)
    results.append(result_dict)
    df_results: pd.DataFrame = pd.DataFrame(results)
    if Path(result_file_path).exists():
        df_old = pd.read_csv(result_file_path)
        df_results = pd.concat([df_old, df_results])
    with open(result_file_path, "w") as filo:
        df_results.to_csv(filo, index=False)


def prepare_framework(knowledge_base_path: str = "/data/service-public-france/extracted/",
                      retriever_type: str = "sparse"):
    """
    Loads ES if needed (check LAUNCH_ES var above) and indexes the knowledge_base corpus
    :param knowledge_base_path: PAth of the folder containing the knowledge_base corpus
    :param retriever_type: The type of retriever to be used
    :return: A Retriever object ready to be queried
    """

    try:
        # kill ES container if running
        subprocess.run(['docker stop $(docker ps -aq)'], shell=True)
        time.sleep(7)

        logging.info("Starting Elasticsearch ...")
        status = subprocess.run(
            ['docker run -d -p 9200:9200 -e "discovery.type=single-node" elasticsearch:7.6.2'], shell=True
        )
        if status.returncode:
            raise Exception(
                "Failed to launch Elasticsearch. If you want to connect to an existing Elasticsearch instance"
                "then set LAUNCH_ELASTICSEARCH in the script to False.")
        time.sleep(15)

        # Connect to Elasticsearch
        document_store = ElasticsearchDocumentStore(host="localhost", username="", password="", index="document")

        dicts = convert_json_files_v10_to_dicts(dir_path=knowledge_base_path)

        # Now, let's write the docs to our DB
        document_store.write_documents(dicts)

        if retriever_type == "sparse":
            retriever = ElasticsearchRetriever(document_store=document_store)
        else:
            retriever = ElasticsearchRetriever(document_store=document_store)

        return retriever
    except Exception as e:
        logger.error(f"Failed with error {str(e)}")


def compute_score(retriever: BaseRetriever, retriever_top_k: int, test_dataset,
                  weight_position: bool = False, filter_level: str = None):
    """
    Given a Retriever to query and its parameters and a test dataset (couple query->true related doc), computes
    the number of matches found by the Retriever. A match is succesful if the retrieved document is among the
    true related doc of the test set.
    :param retriever: A Retriever object
    :param retriever_top_k: The number of docs to retrieve
    :param test_dataset: A collection of "query":[relevant_doc_1, relevant_doc_2, ...]
    :param weight_position: Whether to take into account the position of the retrieved result in the accuracy computation
    :param filter_level: The name of the filter requested, usually the level from the arborescence : 'theme', 'dossier' ..
    :return: Returns mean_precision, avg_time, and detailed_results
    """
    summed_precision = 0
    found_fiche = 0
    nb_questions = 0
    succeses = []
    errors = []
    if weight_position:
        logger.info("Using position weighted accuracy")
    pbar = tqdm(total=len(test_dataset))
    for question, meta in test_dataset.items():
        arborescence = meta['arbo']
        filter_value = arborescence[filter_level]
        if filter_level is not None and filter_value == '': #sometimes the value for the filter is not present in the data
            continue
        true_fiche_urls = meta['urls']
        true_fiche_ids = [f.split("/")[-1] for f in true_fiche_urls]
        if filter_level == None:
            retrieved_results = retriever.retrieve(query=question, top_k=retriever_top_k)
        else:
            retrieved_results = retriever.retrieve(query=question, filters={filter_level: [filter_value]}, top_k=retriever_top_k)
        pbar.update()
        retrieved_doc_names = [f.meta["name"] for f in retrieved_results]
        precision = compute_retriever_precision(true_fiche_ids, retrieved_doc_names, weight_position=weight_position)
        summed_precision += precision
        nb_questions += 1
        if precision:
            found_fiche += 1
            succeses.append({"question": question,
                             "pred_fiche": retrieved_doc_names,
                             "true_fiche": true_fiche_ids,
                             })
        else:
            errors.append({"question": question,
                           "pred_fiche": retrieved_doc_names,
                           "true_fiche": true_fiche_ids,
                           })

    avg_time = pbar.avg_time
    if avg_time is None: #quick fix for a bug idk why is happening
        avg_time = 0
    pbar.close()
    detailed_results = {"successes": succeses, "errors": errors, "avg_time": avg_time}

    mean_precision = summed_precision / nb_questions
    tqdm.write(
        f"The retriever correctly found {found_fiche} fiches among {nb_questions}. Mean_precision {mean_precision}. "
        f"Time per ES query (ms): {avg_time * 1000:.3f}")
    return mean_precision, avg_time, found_fiche, detailed_results, nb_questions


if __name__ == '__main__':
    parser = argopt(__doc__).parse_args()
    test_corpus_path = parser.test_corpus_path
    knowledge_base_path = parser.knowledge_base_path
    result_file_path = parser.result_file_path
    retriever_type = parser.retriever_type

    weight_position = True
    for filter_level in [None, 'theme', 'dossier']:
        for k in range(3,6,2):
            main(test_corpus_path=test_corpus_path, knowledge_base_path=knowledge_base_path,
                 result_file_path=result_file_path, retriever_type=retriever_type, filter_level=filter_level, k_value=k,
                 weight_position=weight_position)