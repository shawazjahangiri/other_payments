from openerp.osv import osv,fields
from openerp.tools.translate import _
from openerp.tools.amount_to_text_en import amount_to_text
from lxml import etree
import time
from openerp.tools import float_compare

class account_voucher(osv.osv):
    _inherit = 'account.voucher'
    _columns = {
                'other_payment_type':fields.selection([('payment','Payment'),('receipt','Receipt'),
                                                       ],'Default Type', readonly=True, states={'draft':[('readonly',False)]}),
                'transaction_type':fields.selection([('cash','Cash'),('cheque','Cheque'),('transfer','Transfer')],'Transaction Type'),
                'cheque_date':fields.date('Cheque Date'),
                'cheque_no':fields.char('Cheque No.'),
                'crossed_cheque':fields.boolean('Crossed'),
                'bank':fields.char('Bank'),
                'beneficiary_name':fields.char('Beneficiary'),
                }
    
    _defaults={
               }
    
    
    
    def onchange_other_payment_type(self,cr,uid,ids,other_payment_type,journal_id ,context=None):
        res = {}
        journal = self.pool.get('account.journal').browse(cr,uid,journal_id)
        transaction_type = False
        print"other_payment_type,journal_id===========",other_payment_type,journal_id
        if other_payment_type:
            type = other_payment_type
            if other_payment_type == 'payment':
                domain = [('type', 'in', ['liquidity', 'payable'])]
            if other_payment_type == 'receipt':
                domain = [('type', 'in', ['liquidity', 'receivable'])]
            if journal.type == 'cash':
                transaction_type = 'cash'
            if journal.type == 'bank':
                transaction_type = 'cheque'
        else:
            type = False
            
        res['value'] = {'type':type,'transaction_type':transaction_type}
        res['domain'] = {'account_id':domain}
        return res
    
    def onchange_journal(self, cr, uid, ids, journal_id, line_ids, tax_id, partner_id, date, amount, ttype, company_id, context=None):
        if context is None:
            context = {}
        if not journal_id:
            return False
        journal_pool = self.pool.get('account.journal')
        journal = journal_pool.browse(cr, uid, journal_id, context=context)
        if ttype in ('sale', 'receipt'):
            account_id = journal.default_debit_account_id
        elif ttype in ('purchase', 'payment'):
            account_id = journal.default_credit_account_id
        else:
            account_id = journal.default_credit_account_id or journal.default_debit_account_id
        tax_id = False
        if account_id and account_id.tax_ids:
            tax_id = account_id.tax_ids[0].id
        
        vals = {'value':{} }
        if ttype in ('sale', 'purchase'):
            vals = self.onchange_price(cr, uid, ids, line_ids, tax_id, partner_id, context)
            vals['value'].update({'tax_id':tax_id,'amount': amount})
        if journal.type in ('bank','cash'):
            if journal.type == 'bank':
                transaction_type = 'cheque'
            elif journal.type =='cash':
                transaction_type = 'cash'
            vals['value'].update({'account_id':journal.default_debit_account_id.id,'transaction_type':transaction_type})
        currency_id = False
        if journal.currency:
            currency_id = journal.currency.id
        else:
            currency_id = journal.company_id.currency_id.id

        period_ids = self.pool['account.period'].find(cr, uid, dt=date, context=dict(context, company_id=company_id))
        vals['value'].update({
            'currency_id': currency_id,
            'payment_rate_currency_id': currency_id,
            'period_id': period_ids and period_ids[0] or False
        })
        #in case we want to register the payment directly from an invoice, it's confusing to allow to switch the journal 
        #without seeing that the amount is expressed in the journal currency, and not in the invoice currency. So to avoid
        #this common mistake, we simply reset the amount to 0 if the currency is not the invoice currency.
        if context.get('payment_expected_currency') and currency_id != context.get('payment_expected_currency'):
            vals['value']['amount'] = 0
            amount = 0
        if partner_id:
            res = self.onchange_partner_id(cr, uid, ids, partner_id, journal_id, amount, currency_id, ttype, date, context)
            for key in res.keys():
                vals[key].update(res[key])
        return vals
    
    def voucher_move_line_create(self, cr, uid, voucher_id, line_total, move_id, company_currency, current_currency, context=None):
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
            if line.other_partner_id:
                partner = line.other_partner_id.id
            else:
                partner =  line.move_line_id.partner_id.id
            
            move_line = {
                'journal_id': voucher.journal_id.id,
                'period_id': voucher.period_id.id,
                'name': line.name or '/',
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
                    'partner_id': line.voucher_id.partner_id.id,
                    'currency_id': line.move_line_id.currency_id.id,
                    'amount_currency': (-1 if line.type == 'cr' else 1) * foreign_currency_diff,
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

    
    def write(self,cr,uid,ids,vals,context=None):
        obj = self.browse(cr,uid,ids)
        if obj.other_payment_type:
            print"obj.other_payment_type==========",obj.other_payment_type
            amount = 0.0
            if 'line_ids' in vals:
                amount = 0.0
                for line in vals['line_ids']:
                    rec = self.pool.get('account.voucher.line').browse(cr,uid,line[1])
                    if line[2]:
                        if 'type' in line[2]:
                            if line[2]['type'] == 'dr':
                                if 'amount' in line[2]:
                                    amount += line[2]['amount']
                                else:
                                    amount +=  rec.amount
                            if line[2]['type'] == 'cr':
                                if 'amount' in line[2]:
                                    amount -= line[2]['amount']
                                else:
                                    amount -=  rec.amount
                        else:
                            if rec.type == 'dr':
                                if 'amount' in line[2]:
                                        amount += line[2]['amount']
                                else:
                                    amount +=  rec.amount
                                    
                            if rec.type == 'cr':
                                if 'amount' in line[2]:
                                        amount -= line[2]['amount']
                                else:
                                    amount -=  rec.amount
                            
                    else:
                        if line[0] != 2:
                            if rec.type == 'dr':
                                    amount +=  rec.amount
                                        
                            if rec.type == 'cr':
                                    amount -=  rec.amount

            else:
                amount = 0.0
                for line in obj.line_ids:
                    if line.type == 'dr':
                        amount +=  line.amount
                    if line.type == 'cr':
                        amount -=  line.amount
            if 'other_payment_type' in vals and vals['other_payment_type']:
                if vals['other_payment_type'] == 'receipt':
                    amount = -amount

                    
            elif obj.other_payment_type == 'receipt':
               amount = -amount
            
            vals['amount'] =  round(amount,2)
            
        res = super(account_voucher,self).write(cr,uid,ids,vals)
        
        return res
    
    
    def onchange_price(self, cr, uid, ids, line_ids, tax_id, partner_id=False,other_payment_type=False, context=None):
        context = context or {}
        tax_pool = self.pool.get('account.tax')
        partner_pool = self.pool.get('res.partner')
        position_pool = self.pool.get('account.fiscal.position')
        if not line_ids:
            line_ids = []
        res = {
            'tax_amount': False,
            'amount': False,
        }
        voucher_total = 0.0

        # resolve the list of commands into a list of dicts
        line_ids = self.resolve_2many_commands(cr, uid, 'line_ids', line_ids, ['amount'], context)

        total_tax = 0.0
        for line in line_ids:
            line_amount = 0.0
            line_amount = line.get('amount',0.0)

            if tax_id:
                tax = [tax_pool.browse(cr, uid, tax_id, context=context)]
                if partner_id:
                    partner = partner_pool.browse(cr, uid, partner_id, context=context) or False
                    taxes = position_pool.map_tax(cr, uid, partner and partner.property_account_position or False, tax, context=context)
                    tax = tax_pool.browse(cr, uid, taxes, context=context)

                if not tax[0].price_include:
                    for tax_line in tax_pool.compute_all(cr, uid, tax, line_amount, 1).get('taxes', []):
                        total_tax += tax_line.get('amount')
            if other_payment_type:
                if not ids:
                    if line['type'] == 'dr':
                        voucher_total += line_amount
                    else:
                        voucher_total -= line_amount
                else:
                    if 'type' in line:
                        if line['type'] == 'dr':
                            voucher_total += line_amount
                        else:
                            voucher_total -= line_amount
                    else:
                        vou_line = self.pool.get('account.voucher.line').browse(cr,uid,line['id'])
                        if vou_line.type =='dr':
                            voucher_total += line['amount']
                        else:
                            voucher_total -= line['amount']
                    
            else:
                voucher_total += line_amount
        total = voucher_total + total_tax
        if other_payment_type == 'receipt':
            total = -total 
        res.update({
            'amount': total or voucher_total,
            'tax_amount': total_tax
        })
        return {
            'value': res
        }
        
        
    def first_move_line_get(self, cr, uid, voucher_id, move_id, company_currency, current_currency, context=None):
        '''
        Return a dict to be use to create the first account move line of given voucher.

        :param voucher_id: Id of voucher what we are creating account_move.
        :param move_id: Id of account move where this line will be added.
        :param company_currency: id of currency of the company to which the voucher belong
        :param current_currency: id of currency of the voucher
        :return: mapping between fieldname and value of account move line to create
        :rtype: dict
        '''
        voucher = self.pool.get('account.voucher').browse(cr,uid,voucher_id,context)
        debit = credit = 0.0
        # TODO: is there any other alternative then the voucher type ??
        # ANSWER: We can have payment and receipt "In Advance".
        # TODO: Make this logic available.
        # -for sale, purchase we have but for the payment and receipt we do not have as based on the bank/cash journal we can not know its payment or receipt
        if voucher.type in ('purchase', 'payment'):
            credit = voucher.paid_amount_in_company_currency
        elif voucher.type in ('sale', 'receipt'):
            debit = voucher.paid_amount_in_company_currency
        if debit < 0: credit = -debit; debit = 0.0
        if credit < 0: debit = -credit; credit = 0.0
        sign = debit - credit < 0 and -1 or 1
        #set the first line of the voucher
        ref = ''
        if voucher.name:
            ref = voucher.name
        if voucher.reference:
            ref += voucher.reference
        move_line = {
                'name': ref or '/',
                'debit': debit,
                'credit': credit,
                'account_id': voucher.account_id.id,
                'move_id': move_id,
                'journal_id': voucher.journal_id.id,
                'period_id': voucher.period_id.id,
                'partner_id': voucher.partner_id.id,
                'currency_id': company_currency <> current_currency and  current_currency or False,
                'amount_currency': (sign * abs(voucher.amount) # amount < 0 for refunds
                    if company_currency != current_currency else 0.0),
                'date': voucher.date,
                'date_maturity': voucher.date_due
            }
        return move_line
    
    
    
class account_voucher_line(osv.osv):
    _inherit = 'account.voucher.line'
    _description = 'Voucher Lines'
    
    
    
    _columns={
              'other_partner_id':fields.many2one('res.partner','Partner'),
              }
    
    
    def onchnge_account_id(self,cr,uid,ids,account_id,type,context=None):
        res = {}
        if type == 'payment':
            res['value'] = {'type':'dr'}
        if type == 'receipt':
            res['value'] = {'type':'cr'}
        return res
    
