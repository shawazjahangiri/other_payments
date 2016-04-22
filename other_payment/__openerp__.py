# -*- coding: utf-8 -*-
{
    'name': 'PDC and Other Payments',
    'version': '1.1',
    'author': 'Shawaz Jahangiri',
    'category': 'Accounting and Payments',

    'summary': 'Single window for other payments and PDC for all cheque payments',
    'description': """
    This module will provide the multiple payments and receipts in single window.
    Also have the Post dated cheque functionality .
    * This contains Two Access right
    - Apply Other Payment : If only other payments wants
    - Apply PDC Payment : If pdc on customer and supplier customer only
    Apply both will give functionalyti for other payment as well as PDC in payments.
    """,

    'depends': ['base','account','account_voucher'],
    'data': [
             'security/security.xml',
             'security/ir.model.access.csv',
             "other_payment_view.xml",
              'account_pdc_view.xml',
             ],
    'demo': [],
     'test': [
         
     ],
     'installable': True,
     'application': True,
     'auto_install': False,

}
