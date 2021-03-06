from conf import conf
from lib import logger
from db import profitDb, keyvDb
from db.conn import pro
from itertools import islice
import time

def iterWindow(seq, n=2):
    it = iter(seq)
    result = tuple(islice(it, n))
    if len(result) == n:
        yield result
    for elem in it:
        result = result[1:] + (elem,)
        yield result

# 计算倍数
def calc_multiple(newV, oldV):
    if oldV<0:
        oldV = -oldV
    if newV > 0 and oldV > 0:
        return newV / oldV
    else:
        return 1


def calc_yoy(newV, oldV):
    if oldV > 0 and newV > 0:
        return 100 * newV / oldV - 100
    else:
        return 0

def singleton(cls):
    _instance = {}

    @wraps(cls)
    def _singleton(*args, **kwargs):
        ck = str(cls) + str(args) + str(kwargs)
        if ck not in _instance:
            _instance[ck] = cls(*args, **kwargs)
        return _instance[ck]

    return _singleton


# @singleton
def get_basic_from_day(ts_code, ann_date):
    basics = pro.daily_basic(
        ts_code=ts_code,
        start_date=ann_date,
        fields="ts_code,trade_date,pe_ttm,pb,float_share,free_share",
    )
    return basics


def parse_basic_by_day(df, ann_date):
    # end_date = (date.strptime('%Y%m%d',ann_date)+timedelta(days=30)).strftime('%Y%m%d')

    try:
        df1 = df[df.trade_date >= ann_date]
    except Exception as e:
        print("b", type(ann_date),ann_date)
        print(df)
        quit()
        raise e

    if len(df1):
        return df1.iloc[-1]
    else:
        return None

@keyvDb.withCache("profitLib", 86400 * 5)
def pullProfitCode(ts_code):
    time.sleep(60/80)
    df = pro.fina_indicator(
        ts_code=ts_code,
        start_date="20150901",
        fields="""
        ann_date,end_date,npta,profit_dedt,q_npta,q_dtprofit,tr_yoy,q_netprofit_yoy, netprofit_yoy,dt_netprofit_yoy,roe_dt
        """.replace(
            " ", ""
        ),
    )
    # netprofit_yoy,dt_netprofit_yoy
    df.fillna(0, inplace=True)
    # df = df[df.q_npta!=0]
    df = df[
        df.apply(
            lambda row: row.end_date[-4:] in ["0331", "0630", "0930", "1231"], axis=1
        )
    ]
    # df.reset_index(drop=True,inplace=True)
    df.rename(
        columns={
            "npta": "netprofit",
            "profit_dedt": "dtprofit",
            "q_npta": "q_netprofit",
            "dt_netprofit_yoy": "dtprofit_yoy",
            "roe_dt": "roe",
        },
        inplace=True,
    )
    # netprofit_yoy,dtprofit_yoy,
    df["code"] = ts_code
    df = df[
        "code,ann_date,end_date,netprofit,dtprofit,netprofit_yoy,dtprofit_yoy,q_netprofit,q_dtprofit,tr_yoy,q_netprofit_yoy,roe".split(
            ","
        )
    ]
    df["q_dtprofit_yoy"] = 0
    df["try"] = 0
    df["ny"] = 1
    df["dny"] = 1
    df["peg"] = 1
    df["pe"] = 0
    df["free_share"] = 0
    df["float_share"] = 0
    df["buy"] = 1
    df_length = len(df)
    if df_length >= 8:
        basicDf = get_basic_from_day(ts_code, df.iloc[-8].ann_date)
    for index, row in df.iterrows():
        # ann_date is None
        if not row.ann_date:
            df.loc[index, 'ann_date'] = row.end_date
            row.ann_date = row.end_date
        # 有些数据index not exists
        if (index+4) not in df.index:
            continue
        # 季度净得增长
        if index + 4 < df_length:
            # debug(index)
            # debug(df)
            # debug(df.loc[index + 4, "q_dtprofit"])
            df.loc[index, "q_dtprofit_yoy"] = calc_yoy(
                row.q_dtprofit, df.loc[index + 4, "q_dtprofit"]
            )

            # 排除利润下滑
            monotonical_num = 0
            q_dtprofit_list = df.loc[index : index + 3, "q_dtprofit"].to_list()

            # 递减的
            for q_dtprofit1, q_dtprofit2 in iterWindow(q_dtprofit_list, 2):
                if q_dtprofit2<=0 or q_dtprofit1 < q_dtprofit2 *.8:
                    monotonical_num += 1
            # 递减太多
            if (
                monotonical_num >= 3
                # and dtprofit_yoy_list[0] < 1 / 2 * dtprofit_yoy_list[3]
            ):
                df.loc[index, "buy"] = 0

        if index + 8 <= df_length:
            df.loc[index, "try"] = df.loc[index : index + 3, "tr_yoy"].mean()
            df.loc[index, "ny"] = ny = calc_multiple(
                df.loc[index : index + 3, "q_netprofit"].sum(),
                df.loc[index + 4 : index + 7, "q_netprofit"].sum(),
            )
            # a1,a2 = df.loc[index : index + 3, "q_dtprofit"].sum(), df.loc[index + 4 : index + 7, "q_dtprofit"].sum()
            dny = calc_multiple(
                df.loc[index : index + 3, "q_dtprofit"].sum(),
                df.loc[index + 4 : index + 7, "q_dtprofit"].sum(),
            )
            # df.loc[index, "dny"] = min(ny, dny)
            df.loc[index, "dny"] = dny

            if row.code == '601992.SH':
                print("coderow:",row)

            # 计算基础数据pe p-e-g
            basic = parse_basic_by_day(basicDf, row.ann_date)
            if basic is not None:
                basic.fillna(0, inplace=True)
                pe = basic.pe_ttm
                dny = df.loc[index, "dny"]
                df.loc[index, "pe"] = 32767 if pe >= 32768 else pe
                df.loc[index, "float_share"] = basic.float_share
                df.loc[index, "free_share"] = basic.free_share
                peg = max(1 + 1 / pe, dny) if pe > 0 else 1
                df.loc[index, "peg"] = peg


    if conf.DEBUG:
        print(df)
    profitCols = set(df.columns) - set(["float_share", "free_share"])
    profitDb.addProfitBatch(df[profitCols])
    # return df[profitCols]
