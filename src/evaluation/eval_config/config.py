parameters = {
    "k": [5],
    "retriever_type": ["dpr"],
    "knowledge_base": ["/home/pavel/code/piaf-ml/data/v11"],
                       # "/home/pavel/code/piaf-ml/data/v10"],
    "test_dataset": ["/home/pavel/code/piaf-ml/data/407_question-fiche_anonym.csv"],
    "weighted_precision": [True],
    "filter_level": [None]
}
# rules:
# corpus and retriever type requires reloading ES indexing
# filtering requires >v10
#