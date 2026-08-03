from database import postgre

MANAGER_TYPES = ["运维经理", "开发经理"]


def load_assets(step_num) -> list[str]:
    if step_num == 2:
        sql_str = r"select application_name from t_business_standard where application_id like '%\_%'"
        postgre.initdatabase()
        data_rows = postgre.select_sql(sql_str)
        postgre.closedatabase()
        system_list = []
        for data_line in data_rows:
            system_list.append(data_line[0])
        print(len(list(set(system_list))))
        sql_str = r"select system_name from t_business_standard where application_id not like '%\_%'"
        postgre.initdatabase()
        base_rows = postgre.select_sql(sql_str)
        postgre.closedatabase()
        print(len(base_rows))
        for base_line in base_rows:
            system_list.append(base_line[0])
        print(len(list(set(system_list))))
        return list(set(system_list))
    else:
        sql_str = "select system_name from t_business_standard where projectclassifi in ('01','02')"
        postgre.initdatabase()
        data_rows = postgre.select_sql(sql_str)
        postgre.closedatabase()
        system_list = []
        for data_line in data_rows:
            system_list.append(data_line[0])
        return list(set(system_list))
