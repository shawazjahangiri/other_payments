# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2010 Tiny SPRL (<http://tiny.be>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

import time
from lxml import etree
from openerp.osv import fields, osv
import openerp.addons.decimal_precision as dp
from openerp.tools.translate import _
from openerp.tools import float_compare
from openerp.report import report_sxw
from openerp import exceptions
import openerp
from openerp import exceptions
from openerp.exceptions import except_orm, Warning, RedirectWarning
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from datetime import datetime



class account_journal(osv.osv): 
    _inherit='account.journal'
    _columns={
              'pdc_payable_account_id':fields.many2one('account.account','PDC Payable'),
              'pdc_receivable_account_id':fields.many2one('account.account','PDC Receivable'),
              
            }

class account_voucher(osv.osv): 
    _inherit='account.voucher'
    
    _columns={
              'pdc_state':fields.selection([('pending','Post Dated'),('cleared','Cleared'),('bounced','Bounced'),('none','None')],'PDC'),
              'pdc_move_id':fields.many2one('account.move','PDC Entry'),
              'cheque_date':fields.date('Cheque Date'),
              'pdc_entry':fields.boolean('PDC Done'),
              'pdc_status':fields.char('PDC'),
              'state':fields.selection(
            [('draft','Draft'),
             ('cancel','Cancelled'),
             ('proforma','Pro-forma'),
             ('pdc', 'PDC'),
             ('posted','Posted')
            ], 'Status', readonly=True, track_visibility='onchange', copy=False,
            help=' * The \'Draft\' status is used when a user is encoding a new and unconfirmed Voucher. \
                        \n* The \'Pro-forma\' when voucher is in Pro-forma status,voucher does not have an voucher number. \
                        \n* The \'Posted\' status is used when user create voucher,a voucher number is generated and voucher entries are created in account \
                        \n* The \'Cancelled\' status is used when user cancel voucher.'),
        

              }

    _defaults = {
                 'pdc_state':'none',
    }
    
    def onchange_pdc_state(self,cr,uid,ids,transaction_type,pdc_state,context=None):
        res={}
        if not ids:
            if transaction_type == 'cheque':
                if pdc_state == 'current':
                    res['value'] = {'cheque_date':date.today()}
                elif pdc_state == 'pending':
                    res['value'] = {'cheque_date':False}
                else:
                    res['value'] = {'cheque_date':False}
            else:
                res['value'] = {'cheque_date':False,'pdc_state':False,'cheque_no':False}
        else:
            if transaction_type == 'cheque':
                if pdc_state == 'none' or pdc_state == 'current':
                    res['value'] = {'cheque_date':date.today()}
                elif pdc_state == 'pending':
                    res['value'] = {'cheque_date':False}
                else:
                    res['value'] = {'cheque_date':False,}
            else:
                res['value'] = {'cheque_date':False,'pdc_state':False,'cheque_no':False}
                    
        return res
    
    """Cancel voucher will cancle and remove PDC entries as well and un reconcile all entries automatically"""
    def cancel_voucher(self, cr, uid, ids, context=None):
        reconcile_pool = self.pool.get('account.move.reconcile')
        move_pool = self.pool.get('account.move')
        move_line_pool = self.pool.get('account.move.line')
        for voucher in self.browse(cr, uid, ids, context=context):
            # refresh to make sure you don't unlink an already removed move
            voucher.refresh()

            reconcile_lst = []
            pdc_reconcile_lst = []
            if voucher.move_id:
                for line in voucher.move_id.line_id:
                    if line.reconcile_id or line.reconcile_partial_id:
                        if line.reconcile_id:
                            reconcile_lst.append((line.id,line.reconcile_id.id))
            if voucher.pdc_move_id:
                for line in voucher.pdc_move_id.line_id:
                    if line.reconcile_id or line.reconcile_partial_id:
                        if line.reconcile_id:
                           pdc_reconcile_lst.append((line.id,line.reconcile_id.id))
                        
            if reconcile_lst:
                for val in reconcile_lst:
                    line_id = val[0]
                    reconcile_id = val[1]
                    qry = "select id from account_move_line where reconcile_id = '"+str(reconcile_id)+"' and id != '"+str(line_id)+"'"
                    cr.execute(qry)
                    temp = cr.fetchall()
                    active_ids = [move_line[0] for move_line in temp]
                    q1 =  "delete from account_move_reconcile where id = '"+str(reconcile_id)+"'" 
                    cr.execute(q1)
                    self.pool.get('account.move.line').reconcile_partial(cr, uid, active_ids, 'manual', context=context)
            
            if pdc_reconcile_lst:
                for val in pdc_reconcile_lst:
                    line_id = val[0]
                    reconcile_id = val[1]
                    qry = "select id from account_move_line where reconcile_id = '"+str(reconcile_id)+"' and id != '"+str(line_id)+"'"
                    cr.execute(qry)
                    temp = cr.fetchall()
                    active_ids = [move_line[0] for move_line in temp]
                    q1 =  "delete from account_move_reconcile where id = '"+str(reconcile_id)+"'" 
                    cr.execute(q1)
                    self.pool.get('account.move.line').reconcile_partial(cr, uid, active_ids, 'manual', context=context)
                    
            for line in voucher.move_ids:
                # refresh to make sure you don't unreconcile an already unreconciled entry
                line.refresh()
                if line.reconcile_id:
                    move_lines = [move_line.id for move_line in line.reconcile_id.line_id]
                    move_lines.remove(line.id)
                    reconcile_pool.unlink(cr, uid, [line.reconcile_id.id])
                    if len(move_lines) >= 2:
                        move_line_pool.reconcile_partial(cr, uid, move_lines, 'auto',context=context)
            
            
            if voucher.move_id:
                move_pool.button_cancel(cr, uid, [voucher.move_id.id])
                query1 = "delete from account_move where id = '"+str(voucher.move_id.id)+"'"
                cr.execute(query1)
            if voucher.pdc_move_id:
                move_pool.button_cancel(cr, uid, [voucher.pdc_move_id.id])
                query2 = "delete from account_move where id = '"+str(voucher.pdc_move_id.id)+"'"
                cr.execute(query2)

                

        res = {
            'state':'cancel',
            'move_id':False,
            'pdc_move_id':False,
            'pdc_entry':False,
               }
        self.write(cr, uid, ids, res)
        if voucher.pdc_status == 'PDC':
            self.write(cr, uid, ids, {'pdc_status':'cancel'})
        else:
            self.write(cr, uid, ids, {'pdc_status':''})    
        return True
    

    def voucher_move_line_create_pdc(self, cr, uid, voucher_id, line_total, move_id, company_currency, current_currency, context=None):
        '''
        Create one account move line, on the given account move, per voucher line where amount is not 0.0.
        It returns Tuple with tot_line what is total of difference between debit and credit and
        a list of lists with ids to be reconciled with this format (total_deb_cred,list_of_lists).

        :param voucher_id: Voucher id what we are working with
        :param line_total: Amount of the first line, which correspond to the amount we should totally split among all voucher lines.
        :param move_id: Account move wher those lines will be joined.
        :param company_currency: id of currency of the company to which the voucher belong
        :param current_currency: id of currency of the voucher
        :return: Tuple build as (remaining amount not allocated on voucher lines, list of account_move_line created in this method)
        :rtype: tuple(float, list of int)
        '''
        if context is None:
            context = {}
        move_line_obj = self.pool.get('account.move.line')
        currency_obj = self.pool.get('res.currency')
        tax_obj = self.pool.get('account.tax')
        tot_line = line_total
        rec_lst_ids = []

        date = self.read(cr, uid, [voucher_id], ['date'], context=context)[0]['date']
        ctx = context.copy()
        ctx.update({'date': date})
        voucher = self.pool.get('account.voucher').browse(cr, uid, voucher_id, context=ctx)
        voucher_currency = voucher.journal_id.currency or voucher.company_id.currency_id
        ctx.update({
            'voucher_special_currency_rate': voucher_currency.rate * voucher.payment_rate ,
            'voucher_special_currency': voucher.payment_rate_currency_id and voucher.payment_rate_currency_id.id or False,})
        prec = self.pool.get('decimal.precision').precision_get(cr, uid, 'Account')
        for line in voucher.line_ids:
            #create one move line per voucher line where amount is not 0.0
            # AND (second part of the clause) only if the original move line was not having debit = credit = 0 (which is a legal value)
            if not line.amount and not (line.move_line_id and not float_compare(line.move_line_id.debit, line.move_line_id.credit, precision_digits=prec) and not float_compare(line.move_line_id.debit, 0.0, precision_digits=prec)):
                continue
            # convert the amount set on the voucher line into the currency of the voucher's company
            # this calls res_curreny.compute() with the right context, so that it will take either the rate on the voucher if it is relevant or will use the default behaviour
            amount = self._convert_amount(cr, uid, line.untax_amount or line.amount, voucher.id, context=ctx)
            # if the amount encoded in voucher is equal to the amount unreconciled, we need to compute the
            # currency rate difference
            if line.amount == line.amount_unreconciled:
                if not line.move_line_id:
                    raise osv.except_osv(_('Wrong voucher line'),_("The invoice you are willing to pay is not valid anymore."))
                sign = voucher.type in ('payment', 'purchase') and -1 or 1
                currency_rate_difference = sign * (line.move_line_id.amount_residual - amount)
            else:
                currency_rate_difference = 0.0
            
            partner = voucher.partner_id.id or False
            
            if voucher.cheque_no:
                li_name = line.name + '/' + voucher.cheque_no
            else:
                li_name = line.name 
            move_line = {
                'journal_id': voucher.journal_id.id,
                'period_id': voucher.period_id.id,
                'name': li_name or '/',
                'account_id': line.account_id.id,
                'move_id': move_id,
                'partner_id': partner,
                'currency_id': line.move_line_id and (company_currency <> line.move_line_id.currency_id.id and line.move_line_id.currency_id.id) or False,
                'analytic_account_id': line.account_analytic_id and line.account_analytic_id.id or False,
                'quantity': 1,
                'credit': 0.0,
                'debit': 0.0,
                'date': voucher.date
            }
            
           
            if amount < 0:
                amount = -amount
                if line.type == 'dr':
                    line.type = 'cr'
                else:
                    line.type = 'dr'

            if (line.type=='dr'):
                tot_line += amount
                move_line['debit'] = amount
            else:
                tot_line -= amount
                move_line['credit'] = amount

            if voucher.tax_id and voucher.type in ('sale', 'purchase'):
                move_line.update({
                    'account_tax_id': voucher.tax_id.id,
                })

            if move_line.get('account_tax_id', False):
                tax_data = tax_obj.browse(cr, uid, [move_line['account_tax_id']], context=context)[0]
                if not (tax_data.base_code_id and tax_data.tax_code_id):
                    raise osv.except_osv(_('No Account Base Code and Account Tax Code!'),_("You have to configure account base code and account tax code on the '%s' tax!") % (tax_data.name))

            # compute the amount in foreign currency
            foreign_currency_diff = 0.0
            amount_currency = False
            if line.move_line_id:
                # We want to set it on the account move line as soon as the original line had a foreign currency
                if line.move_line_id.currency_id and line.move_line_id.currency_id.id != company_currency:
                    # we compute the amount in that foreign currency.
                    if line.move_line_id.currency_id.id == current_currency:
                        # if the voucher and the voucher line share the same currency, there is no computation to do
                        sign = (move_line['debit'] - move_line['credit']) < 0 and -1 or 1
                        amount_currency = sign * (line.amount)
                    else:
                        # if the rate is specified on the voucher, it will be used thanks to the special keys in the context
                        # otherwise we use the rates of the system
                        amount_currency = currency_obj.compute(cr, uid, company_currency, line.move_line_id.currency_id.id, move_line['debit']-move_line['credit'], context=ctx)
                if line.amount == line.amount_unreconciled:
                    sign = voucher.type in ('payment', 'purchase') and -1 or 1
                    foreign_currency_diff = sign * line.move_line_id.amount_residual_currency + amount_currency

            move_line['amount_currency'] = amount_currency
            
            voucher_line = move_line_obj.create(cr, uid, move_line)
            rec_ids = [voucher_line, line.move_line_id.id]

            if not currency_obj.is_zero(cr, uid, voucher.company_id.currency_id, currency_rate_difference):
                # Change difference entry in company currency
                exch_lines = self._get_exchange_lines(cr, uid, line, move_id, currency_rate_difference, company_currency, current_currency, context=context)
                new_id = move_line_obj.create(cr, uid, exch_lines[0],context)
                move_line_obj.create(cr, uid, exch_lines[1], context)
                rec_ids.append(new_id)

            if line.move_line_id and line.move_line_id.currency_id and not currency_obj.is_zero(cr, uid, line.move_line_id.currency_id, foreign_currency_diff):
                # Change difference entry in voucher currency
                move_line_foreign_currency = {
                    'journal_id': line.voucher_id.journal_id.id,
                    'period_id': line.voucher_id.period_id.id,
                    'name': _('change')+': '+(line.name or '/'),
                    'account_id': line.account_id.id,
                    'move_id': move_id,
                    'partner_id': line.voucher_id.partner_id.id,
                    'currency_id': line.move_line_id.currency_id.id,
                    'amount_currency': -1 * foreign_currency_diff,
                    'quantity': 1,
                    'credit': 0.0,
                    'debit': 0.0,
                    'date': line.voucher_id.date,
                }

                new_id = move_line_obj.create(cr, uid, move_line_foreign_currency, context=context)
                rec_ids.append(new_id)
            if line.move_line_id.id:
                rec_lst_ids.append(rec_ids)
        return (tot_line, rec_lst_ids)

    def action_move_line_create_pdc(self, cr, uid, ids, context=None):
        '''
        Confirm the vouchers given in ids and create the journal entries for each of them
        '''
        if context is None:
            context = {}
        move_pool = self.pool.get('account.move')
        move_line_pool = self.pool.get('account.move.line')
        for voucher in self.browse(cr, uid, ids, context=context):
            move_line_val={}
            local_context = dict(context, force_company=voucher.journal_id.company_id.id)
            if voucher.move_id:
                continue
            company_currency = self._get_company_currency(cr, uid, voucher.id, context)
            current_currency = self._get_current_currency(cr, uid, voucher.id, context)
            # we select the context to use accordingly if it's a multicurrency case or not
            context = self._sel_context(cr, uid, voucher.id, context)
            # But for the operations made by _convert_amount, we always need to give the date in the context
            ctx = context.copy()
            ctx.update({'date': voucher.date})
            if voucher.cheque_date <= voucher.date:
                raise exceptions.ValidationError(" PDC Date must be greater than payment date")
                
            # Create the account move record.
            
            move_id = move_pool.create(cr, uid, self.account_move_get(cr, uid, voucher.id, context=context), context=context)
            # Get the name of the account_move just created
            move_pool.write(cr,uid,[move_id],{'pdc_rel_status':'PDC'})
            name = move_pool.browse(cr, uid, move_id, context=context).name
            # Create the first line of the voucher
            move_line_val = self.first_move_line_get(cr,uid,voucher.id, move_id, company_currency, current_currency, local_context)
            if voucher.type in ('purchase', 'payment'):
                pdc_account = voucher.journal_id.pdc_payable_account_id.id
            elif voucher.type in ('sale', 'receipt'):
                pdc_account = voucher.journal_id.pdc_receivable_account_id.id
            if not pdc_account:
                raise exceptions.ValidationError(" PDC Account not define in journal")
            move_line_val.update({'name':str(voucher.cheque_no) +'/'+'PDC','ref':str(voucher.narration) + '/PDC','account_id':pdc_account})

            move_line_id = move_line_pool.create(cr, uid, move_line_val, local_context)
            move_line_brw = move_line_pool.browse(cr, uid, move_line_id, context=context)
            line_total = move_line_brw.debit - move_line_brw.credit
            rec_list_ids = []
            if voucher.type == 'sale':
                line_total = line_total - self._convert_amount(cr, uid, voucher.tax_amount, voucher.id, context=ctx)
            elif voucher.type == 'purchase':
                line_total = line_total + self._convert_amount(cr, uid, voucher.tax_amount, voucher.id, context=ctx)
            # Create one move line per voucher line where amount is not 0.0
            line_total, rec_list_ids = self.voucher_move_line_create_pdc(cr, uid, voucher.id, line_total, move_id, company_currency, current_currency, context)
            
            move_line_trade={}
            move_line_id1=False
            trade_acc=False
            if not rec_list_ids:
                if voucher.type in ('purchase', 'payment'):
                    trade_acc = voucher.partner_id.property_account_payable.id
                    if voucher.cheque_no:
                        li_name = move_line_brw.move_id.name +'/' + voucher.cheque_no
                    else:
                        li_name = move_line_brw.move_id.name
                    move_line_trade = {
                    'journal_id': voucher.journal_id.id,
                    'period_id': voucher.period_id.id,
                    'name': li_name or '/',
                    'account_id': trade_acc,
                    'move_id': move_id,
                    'partner_id': voucher.partner_id.id,
                    'currency_id': move_line_brw and (company_currency <> move_line_brw.currency_id.id and move_line_brw.currency_id.id) or False,
#                     'analytic_account_id': line.account_analytic_id and line.account_analytic_id.id or False,
                    'quantity': 1,
                    'credit': 0.0,
                    'debit': voucher.amount,
                    'date': voucher.date
                    } 
                    
                    
                    
                                   
                
                elif voucher.type in ('sale', 'receipt'):
                    trade_acc = voucher.partner_id.property_account_receivable.id
                    if voucher.cheque_no:
                        li_name = move_line_brw.move_id.name +'/' + voucher.cheque_no
                    else:
                        li_name = move_line_brw.move_id.name
                    move_line_trade = {
                    'journal_id': voucher.journal_id.id,
                    'period_id': voucher.period_id.id,
                    'name': li_name or '/',
                    'account_id': trade_acc,
                    'move_id': move_id,
                    'partner_id': voucher.partner_id.id,
                    'currency_id': move_line_brw and (company_currency <> move_line_brw.currency_id.id and move_line_brw.currency_id.id) or False,
                    # 'analytic_account_id': line.account_analytic_id and line.account_analytic_id.id or False,
                    'quantity': 1,
                    'credit': voucher.amount,
                    'debit': 0.0,
                    'date': voucher.date
                                       }

                
            ml_writeoff = self.writeoff_move_line_get(cr, uid, voucher.id, line_total, move_id, name, company_currency, current_currency, local_context)
            if ml_writeoff:
               move_line_pool.create(cr, uid, ml_writeoff, local_context)
            # We post the voucher.
            #if voucher.partner_id.is_company:
            
            #if voucher.partner_id.is_company:

            

            self.write(cr, uid, [voucher.id], {
                'pdc_move_id': move_id,
                'pdc_state': 'pending',
                'number': name,
            })
            if voucher.journal_id.entry_posted:
                move_pool.post(cr, uid, [move_id], context={})
            # We automatically reconcile the account move lines.
            reconcile = False
            for rec_ids in rec_list_ids:
                if len(rec_ids) >= 2:
                    reconcile = move_line_pool.reconcile_partial(cr, uid, rec_ids, writeoff_acc_id=voucher.writeoff_acc_id.id, writeoff_period_id=voucher.period_id.id, writeoff_journal_id=voucher.journal_id.id)
        return True    


    def pdc_voucher(self, cr, uid, ids, context=None):
        obj = self.browse(cr,uid,ids[0])

        self.action_move_line_create_pdc(cr, uid, ids, context=context)
        self.pool.get('account.move').button_validate(cr,uid,[obj.pdc_move_id.id],context=context)
        
        self.write(cr, uid, ids, {
                    'pdc_entry': True,
                    'pdc_status':'PDC',
                    'state':'pdc',
                })
        return True
    
    ### PDC FOR PETTY CASH-----
    
    def voucher_move_line_create_petty_pdc(self, cr, uid, voucher_id, line_total, move_id, company_currency, current_currency, context=None):
        '''
        Create one account move line, on the given account move, per voucher line where amount is not 0.0.
        It returns Tuple with tot_line what is total of difference between debit and credit and
        a list of lists with ids to be reconciled with this format (total_deb_cred,list_of_lists).

        :param voucher_id: Voucher id what we are working with
        :param line_total: Amount of the first line, which correspond to the amount we should totally split among all voucher lines.
        :param move_id: Account move wher those lines will be joined.
        :param company_currency: id of currency of the company to which the voucher belong
        :param current_currency: id of currency of the voucher
        :return: Tuple build as (remaining amount not allocated on voucher lines, list of account_move_line created in this method)
        :rtype: tuple(float, list of int)
        '''
        if context is None:
            context = {}
        move_line_obj = self.pool.get('account.move.line')
        currency_obj = self.pool.get('res.currency')
        tax_obj = self.pool.get('account.tax')
        tot_line = line_total
        rec_lst_ids = []
        
        date = self.read(cr, uid, [voucher_id], ['date'], context=context)[0]['date']
        ctx = context.copy()
        ctx.update({'date': date})
        voucher = self.pool.get('account.voucher').browse(cr, uid, voucher_id, context=ctx)
        voucher_currency = voucher.journal_id.currency or voucher.company_id.currency_id
        ctx.update({
            'voucher_special_currency_rate': voucher_currency.rate * voucher.payment_rate ,
            'voucher_special_currency': voucher.payment_rate_currency_id and voucher.payment_rate_currency_id.id or False,})
        prec = self.pool.get('decimal.precision').precision_get(cr, uid, 'Account')
        for line in voucher.line_ids:
            #create one move line per voucher line where amount is not 0.0
            # AND (second part of the clause) only if the original move line was not having debit = credit = 0 (which is a legal value)
            if not line.amount and not (line.move_line_id and not float_compare(line.move_line_id.debit, line.move_line_id.credit, precision_digits=prec) and not float_compare(line.move_line_id.debit, 0.0, precision_digits=prec)):
                continue
            # convert the amount set on the voucher line into the currency of the voucher's company
            # this calls res_curreny.compute() with the right context, so that it will take either the rate on the voucher if it is relevant or will use the default behaviour
            amount = self._convert_amount(cr, uid, line.untax_amount or line.amount, voucher.id, context=ctx)
            # if the amount encoded in voucher is equal to the amount unreconciled, we need to compute the
            # currency rate difference
            if line.amount == line.amount_unreconciled:
                if not line.move_line_id:
                    raise osv.except_osv(_('Wrong voucher line'),_("The invoice you are willing to pay is not valid anymore."))
                sign = line.type =='dr' and -1 or 1
                currency_rate_difference = sign * (line.move_line_id.amount_residual - amount)
            else:
                currency_rate_difference = 0.0
            move_line = {
                'journal_id': voucher.journal_id.id,
                'period_id': voucher.period_id.id,
                'name': line.name or '/',
                'account_id': line.account_id.id,
                'move_id': move_id,
                'partner_id': line.other_partner_id or line.other_partner_id.id or False,
                'currency_id': line.move_line_id and (company_currency <> line.move_line_id.currency_id.id and line.move_line_id.currency_id.id) or False,
                'analytic_account_id': line.account_analytic_id and line.account_analytic_id.id or False,
                'quantity': 1,
                'credit': 0.0,
                'debit': 0.0,
                'date': voucher.date
            }
            

            
            if amount < 0:
                amount = -amount
                if line.type == 'dr':
                    line.type = 'cr'
                else:
                    line.type = 'dr'

            if (line.type=='dr'):
                tot_line += amount
                move_line['debit'] = amount
            else:
                tot_line -= amount
                move_line['credit'] = amount

            if voucher.tax_id and voucher.type in ('sale', 'purchase'):
                move_line.update({
                    'account_tax_id': voucher.tax_id.id,
                })

            if move_line.get('account_tax_id', False):
                tax_data = tax_obj.browse(cr, uid, [move_line['account_tax_id']], context=context)[0]
                if not (tax_data.base_code_id and tax_data.tax_code_id):
                    raise osv.except_osv(_('No Account Base Code and Account Tax Code!'),_("You have to configure account base code and account tax code on the '%s' tax!") % (tax_data.name))

            # compute the amount in foreign currency
            foreign_currency_diff = 0.0
            amount_currency = False
            if line.move_line_id:
                # We want to set it on the account move line as soon as the original line had a foreign currency
                if line.move_line_id.currency_id and line.move_line_id.currency_id.id != company_currency:
                    # we compute the amount in that foreign currency.
                    if line.move_line_id.currency_id.id == current_currency:
                        # if the voucher and the voucher line share the same currency, there is no computation to do
                        sign = (move_line['debit'] - move_line['credit']) < 0 and -1 or 1
                        amount_currency = sign * (line.amount)
                    else:
                        # if the rate is specified on the voucher, it will be used thanks to the special keys in the context
                        # otherwise we use the rates of the system
                        amount_currency = currency_obj.compute(cr, uid, company_currency, line.move_line_id.currency_id.id, move_line['debit']-move_line['credit'], context=ctx)
                if line.amount == line.amount_unreconciled:
                    foreign_currency_diff = line.move_line_id.amount_residual_currency - abs(amount_currency)

            move_line['amount_currency'] = amount_currency
            voucher_line = move_line_obj.create(cr, uid, move_line)
            rec_ids = [voucher_line, line.move_line_id.id]

            if not currency_obj.is_zero(cr, uid, voucher.company_id.currency_id, currency_rate_difference):
                # Change difference entry in company currency
                exch_lines = self._get_exchange_lines(cr, uid, line, move_id, currency_rate_difference, company_currency, current_currency, context=context)
                new_id = move_line_obj.create(cr, uid, exch_lines[0],context)
                move_line_obj.create(cr, uid, exch_lines[1], context)
                rec_ids.append(new_id)

            if line.move_line_id and line.move_line_id.currency_id and not currency_obj.is_zero(cr, uid, line.move_line_id.currency_id, foreign_currency_diff):
                # Change difference entry in voucher currency
                move_line_foreign_currency = {
                    'journal_id': line.voucher_id.journal_id.id,
                    'period_id': line.voucher_id.period_id.id,
                    'name': _('change')+': '+(line.name or '/'),
                    'account_id': line.account_id.id,
                    'move_id': move_id,
                    'partner_id': line.petty_partner_id.id,
                    'currency_id': line.move_line_id.currency_id.id,
                    'amount_currency': -1 * foreign_currency_diff,
                    'quantity': 1,
                    'credit': 0.0,
                    'debit': 0.0,
                    'date': line.voucher_id.date,
                }
                

                new_id = move_line_obj.create(cr, uid, move_line_foreign_currency, context=context)
                rec_ids.append(new_id)
            if line.move_line_id.id:
                rec_lst_ids.append(rec_ids)
        return (tot_line, rec_lst_ids)
    
    def action_move_line_create_petty_pdc(self, cr, uid, ids, context=None):
        '''
        Confirm the vouchers given in ids and create the journal entries for each of them
        '''
        if context is None:
            context = {}
        move_pool = self.pool.get('account.move')
        move_line_pool = self.pool.get('account.move.line')
        for voucher in self.browse(cr, uid, ids, context=context):
            move_line_val={}
            local_context = dict(context, force_company=voucher.journal_id.company_id.id)
            if voucher.move_id:
                continue
            company_currency = self._get_company_currency(cr, uid, voucher.id, context)
            current_currency = self._get_current_currency(cr, uid, voucher.id, context)
            # we select the context to use accordingly if it's a multicurrency case or not
            context = self._sel_context(cr, uid, voucher.id, context)
            # But for the operations made by _convert_amount, we always need to give the date in the context
            ctx = context.copy()
            ctx.update({'date': voucher.date})
            if voucher.cheque_date <= voucher.date:
                raise exceptions.ValidationError(" PDC Date must be greater than payment date")
                
            # Create the account move record.
            
            move_id = move_pool.create(cr, uid, self.account_move_get(cr, uid, voucher.id, context=context), context=context)
            # Get the name of the account_move just created
            move_pool.write(cr,uid,[move_id],{'pdc_rel_status':'PDC'})
            name = move_pool.browse(cr, uid, move_id, context=context).name
            # Create the first line of the voucher
            move_line_val = self.first_move_line_get(cr,uid,voucher.id, move_id, company_currency, current_currency, local_context)
            if voucher.type in ('purchase', 'payment'):
                pdc_account = voucher.journal_id.pdc_payable_account_id.id
            elif voucher.type in ('sale', 'receipt'):
                pdc_account = voucher.journal_id.pdc_receivable_account_id.id
            move_line_val.update({'name':str(voucher.cheque_no)+'/'+'PDC','ref':str(voucher.narration) + '/PDC','account_id':pdc_account})
#             if voucher.location_id and voucher.salesman_id:
#                 move_line_val.update({'location_id':voucher.location_id.id,'salesman_id':voucher.salesman_id.id})
#             if voucher.cost_centre_id:
#                 move_line_val.update({'cost_centre_id':voucher.cost_centre_id.id}) 
            move_line_id = move_line_pool.create(cr, uid, move_line_val, local_context)
            move_line_brw = move_line_pool.browse(cr, uid, move_line_id, context=context)
            line_total = move_line_brw.debit - move_line_brw.credit
            rec_list_ids = []
            if voucher.type == 'sale':
                line_total = line_total - self._convert_amount(cr, uid, voucher.tax_amount, voucher.id, context=ctx)
            elif voucher.type == 'purchase':
                line_total = line_total + self._convert_amount(cr, uid, voucher.tax_amount, voucher.id, context=ctx)
            # Create one move line per voucher line where amount is not 0.0
            line_total, rec_list_ids = self.voucher_move_line_create_petty_pdc(cr, uid, voucher.id, line_total, move_id, company_currency, current_currency, context)

            self.write(cr, uid, [voucher.id], {
                'pdc_move_id': move_id,
                'pdc_state': 'pending',
                'number': name,
            })
            if voucher.journal_id.entry_posted:
                move_pool.post(cr, uid, [move_id], context={})
            # We automatically reconcile the account move lines.
            reconcile = False
            for rec_ids in rec_list_ids:
                if len(rec_ids) >= 2:
                    reconcile = move_line_pool.reconcile_partial(cr, uid, rec_ids, writeoff_acc_id=voucher.writeoff_acc_id.id, writeoff_period_id=voucher.period_id.id, writeoff_journal_id=voucher.journal_id.id)
        return True    

    
    def pdc_voucher_custom(self, cr, uid, ids, context=None):
        self.action_move_line_create_petty_pdc(cr, uid, ids, context=context)
        obj = self.browse(cr,uid,ids[0])
        self.pool.get('account.move').button_validate(cr,uid,[obj.pdc_move_id.id],context=context)
        self.write(cr, uid, ids, {
                    'pdc_entry': True,
                    'pdc_status':'PDC',
                    'state':'pdc',
                })
        return True
      
      
      
      
    def action_move_line_create(self, cr, uid, ids, context=None):
        '''
        Confirm the vouchers given in ids and create the journal entries for each of them
        '''
        if context is None:
            context = {}
        move_pool = self.pool.get('account.move')
        move_line_pool = self.pool.get('account.move.line')
        for voucher in self.browse(cr, uid, ids, context=context):
            if voucher.pdc_state == 'pending' and voucher.state == 'draft':
                raise osv.except_osv(_('Warning!'),
                    _('Please first PDC then validate !'))
            if voucher.pdc_state == 'current' and voucher.cheque_date > time.strftime('%Y-%m-%d'):
                raise osv.except_osv(_('Warning!'),
                    _('Please Select Correct Cheque Date !'))
            move_line_val_one={}

            if voucher.pdc_state=='pending':
                local_context = dict(context, force_company=voucher.journal_id.company_id.id)
                if voucher.move_id:
                    continue
                company_currency = self._get_company_currency(cr, uid, voucher.id, context)
                current_currency = self._get_current_currency(cr, uid, voucher.id, context)
                # we select the context to use accordingly if it's a multicurrency case or not
                context = self._sel_context(cr, uid, voucher.id, context)
                # But for the operations made by _convert_amount, we always need to give the date in the context
                ctx = context.copy()
                ctx.update({'date': voucher.date})
                # Create the account move record.
                self.write(cr,uid,ids,{'pdc_status':'RLS'})
                move_id = move_pool.create(cr, uid, self.account_move_get(cr, uid, voucher.id, context=context), context=context)
                # Get the name of the account_move just created
                move_pool.write(cr,uid,[move_id],{'pdc_rel_status':'Release','date':voucher.cheque_date})
                name = move_pool.browse(cr, uid, move_id, context=context).name
                # Create the first line of the voucher
                move_line_val = self.first_move_line_get(cr,uid,voucher.id, move_id, company_currency, current_currency, local_context)
                move_line_val_one = self.first_move_line_get(cr,uid,voucher.id, move_id, company_currency, current_currency, local_context)
                if move_line_val['credit']>0.0:
                    if voucher.type in ('sale', 'receipt') and not voucher.other_payment_type:
                        move_line_val['credit'] = voucher.amount
                    
                    move_line_val_one['debit']=move_line_val['credit']
                    move_line_val['debit']=0.0
                    move_line_val_one['credit']=0.0
                else:
                    if voucher.type in ('sale', 'receipt') and not voucher.other_payment_type:
                        move_line_val['debit'] = voucher.amount
                        
                    move_line_val_one['credit']=move_line_val['debit']
                    move_line_val['credit']=0.0
                    move_line_val_one['debit']=0.0
                if voucher.type in ('purchase', 'payment'):
                    pdc_account = voucher.journal_id.pdc_payable_account_id.id
                elif voucher.type in ('sale', 'receipt'):
                    pdc_account = voucher.journal_id.pdc_receivable_account_id.id
                move_line_val_one.update({'name':str(voucher.cheque_no) +'/' +'RLS','ref':str(voucher.narration) + '/PDC','account_id':pdc_account})

                move_line_id1 = move_line_pool.create(cr, uid, move_line_val, local_context)
                move_line_brw1 = move_line_pool.browse(cr, uid, move_line_id1, context=context)
                
                move_line_id = move_line_pool.create(cr, uid, move_line_val_one, local_context)
                move_line_brw = move_line_pool.browse(cr, uid, move_line_id, context=context)
                line_total = move_line_brw.debit - move_line_brw.credit
                self.write(cr, uid, [voucher.id], {
                    'move_id': move_id,
                    'state': 'posted',
                    'number': name,
                })
                if voucher.journal_id.entry_posted:
                    move_pool.post(cr, uid, [move_id], context={})
                # We automatically reconcile the account move lines.
                reconcile = False
                # for rec_ids in rec_list_ids:
                #     if len(rec_ids) >= 2:
                #         reconcile = move_line_pool.reconcile_partial(cr, uid, rec_ids, writeoff_acc_id=voucher.writeoff_acc_id.id, writeoff_period_id=voucher.period_id.id, writeoff_journal_id=voucher.journal_id.id)
                        
            else:
                local_context = dict(context, force_company=voucher.journal_id.company_id.id)
                if voucher.move_id:
                    continue
                company_currency = self._get_company_currency(cr, uid, voucher.id, context)
                current_currency = self._get_current_currency(cr, uid, voucher.id, context)
                # we select the context to use accordingly if it's a multicurrency case or not
                context = self._sel_context(cr, uid, voucher.id, context)
                # But for the operations made by _convert_amount, we always need to give the date in the context
                ctx = context.copy()
                ctx.update({'date': voucher.date})
                # Create the account move record.

                move_id = move_pool.create(cr, uid, self.account_move_get(cr, uid, voucher.id, context=context), context=context)
                # Get the name of the account_move just created
                move_pool_id = move_pool.browse(cr, uid, move_id, context=context)
                name = move_pool.browse(cr, uid, move_id, context=context).name
                # Create the first line of the voucher
                if voucher.type or voucher.journal_id.type in ('purchase','sale','purchase_refund'):
                    move_line_id = move_line_pool.create(cr, uid, self.first_move_line_get(cr,uid,voucher.id, move_id, company_currency, current_currency, local_context), local_context)
                else:
                    move_line_id = 0

                move_line_brw = move_line_pool.browse(cr, uid, move_line_id, context=context)
                
                      
                line_total = move_line_brw.debit - move_line_brw.credit
                rec_list_ids = []
                if voucher.type == 'sale':
                    line_total = line_total - self._convert_amount(cr, uid, voucher.tax_amount, voucher.id, context=ctx)
                elif voucher.type == 'purchase':
                    line_total = line_total + self._convert_amount(cr, uid, voucher.tax_amount, voucher.id, context=ctx)
                # Create one move line per voucher line where amount is not 0.0
                line_total, rec_list_ids = self.voucher_move_line_create(cr, uid, voucher.id, line_total, move_id, company_currency, current_currency, context)
                # line_total, rec_list_ids = self.voucher_move_line_create_pdc(cr, uid, voucher.id, line_total, move_id, company_currency, current_currency, context)
                # Create the writeoff line if needed
                #if voucher.partner_id.is_company:
                     
                ml_writeoff = self.writeoff_move_line_get(cr, uid, voucher.id, line_total, move_id, name, company_currency, current_currency, local_context)

                if ml_writeoff:
                    move_line_id1 = move_line_pool.create(cr, uid, ml_writeoff, local_context)

                       
                # We post the voucher.
                #if voucher.partner_id.is_company:

                self.write(cr, uid, [voucher.id], {
                    'move_id': move_id,
                    'state': 'posted',
                    'number': name,
                })
                if voucher.journal_id.entry_posted:
                    move_pool.post(cr, uid, [move_id], context={})
                # We automatically reconcile the account move lines.
                reconcile = False
                for rec_ids in rec_list_ids:
                    if len(rec_ids) >= 2:
                        reconcile = move_line_pool.reconcile_partial(cr, uid, rec_ids, writeoff_acc_id=voucher.writeoff_acc_id.id, writeoff_period_id=voucher.period_id.id, writeoff_journal_id=voucher.journal_id.id)
        return True
    

          
