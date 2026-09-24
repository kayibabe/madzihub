
import numpy as np
def detect_anomalies(series):
    if not series: return []
    mean, std = np.mean(series), np.std(series)
    return [{"index":i,"value":float(v)} for i,v in enumerate(series) if abs(v-mean)>2*std]
