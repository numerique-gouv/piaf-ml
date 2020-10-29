parameters = {
    "k": [30,100],
    "retriever_type": ["sparse",'dense'],
    "knowledge_base": ["./data/v11"],
                       # "/home/pavel/code/piaf-ml/data/v10"],
    "test_dataset": ["./data/407_question-fiche_anonym.csv"],
    "weighted_precision": [True],
    "filter_level": ['theme','dossier'],
    "lemma_preprocessing": [False, True]
}
# rules:
# corpus and retriever type requires reloading ES indexing
# filtering requires >v10
#
