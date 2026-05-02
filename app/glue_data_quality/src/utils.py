def rules_list_to_dqdl(rules_list):
    """
    Converte uma lista de regras em string DQDL para o Glue Data Quality.
    Exemplo:
        ["IsComplete 'id'", "RowCount > 0"]
    vira:
        Rules = [
            IsComplete 'id',
            RowCount > 0
        ]
    """
    if not rules_list:
        return "Rules = [\n    RowCount > 0\n]"
    rules = ",\n    ".join(rules_list)
    return f"Rules = [\n    {rules}\n]"
