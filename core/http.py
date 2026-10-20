# -*- coding: utf-8 -*-
"""ردود JSON الموحّدة ({status, data|message}) وقراءة معاملات الطلب.
منقول من app.py بلا تغيير (Phase 4 / A2)."""
from flask import jsonify, request

def ok_json(data):
    return jsonify({"status": "ok", "data": data})


def err_json(msg, code=400):
    return jsonify({"status": "error", "message": msg}), code


def _opt_int_arg(name):
    v = str(request.args.get(name, "") or "").strip()
    return int(v) if v else None   # ValueError على قيمة غير رقمية


def _opt_float_arg(name):
    v = str(request.args.get(name, "") or "").strip()
    return float(v) if v else None   # ValueError على قيمة غير رقمية
