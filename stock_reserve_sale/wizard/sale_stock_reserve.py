# Copyright 2013 Camptocamp SA - Guewen Baconnier
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
# import logging

from odoo import _, api, exceptions, fields, models

# _logger = logging.getLogger(__name__)

class SaleStockReserve(models.TransientModel):
    _name = "sale.stock.reserve"
    _description = "Sale Stock Reserve"

    @api.model
    def _default_location_id(self):
        model = self.env[self.env.context["active_model"]]
        locations = {}
        if model._name == "sale.order":
            order = model.browse(self.env.context["active_id"])
            lines = order.order_line
            pickings = self._default_picking_type_id()
            if pickings:
                locations = {pickings.default_location_src_id}
            else:
                locations = {o.warehouse_id.lot_stock_id for o in order}
        else:
            lines = model.browse(self.env.context["active_ids"])
            pickings = self._default_picking_type_id()
            if pickings:
                locations = {pickings.default_location_src_id}
            else:
                locations = {l.order_id.warehouse_id.lot_stock_id for l in lines}
        
        try:
            locations
            # locations = {l.warehouse_id.wh_output_stock_loc_id for l in lines}
        except AttributeError:
            self.env["stock.reservation"]
            # prevent attributerror if no location

        if len(locations) == 1:
            return locations.pop()
        elif len(locations) > 1:
            raise exceptions.Warning(
                _(
                    """The lines have different locations. Please reserve them
                    individually with the reserve button on each one."""
                )
            )

        return self.env["stock.reservation"]

    @api.model
    def _default_location_dest_id(self):
        return self.env["stock.reservation"]._default_location_dest_id()
    
    @api.model
    def _default_picking_type_id(self):
        model = self.env[self.env.context["active_model"]]
        ProcurementRule = self.env["procurement.rule"]
        Warehouse = self.env["stock.warehouse"]
        pickings = {}
        if model._name == "sale.order":
            order = model.browse(self.env.context["active_id"])
            lines = order.order_line
            try:
                route_ids = [l.route_id for l in lines]
                if route_ids:
                    route_pull_ids = []
                    for route in route_ids:
                        pull_ids = [p.id for rt in route for p in rt.pull_ids]
                        route_pull_ids += ProcurementRule.search(
                            [
                                ("id", "in", pull_ids),
                                ("active", "=", True),
                            ],
                            order="route_sequence asc, sequence asc",
                            limit=1,
                        )
                    if route_pull_ids:
                        pickings = {p.picking_type_id.warehouse_id.int_type_id for p in route_pull_ids}
                else:
                    pickings = {o.warehouse_id.int_type_id for o in order}
            except AttributeError:
                self.env["stock.reservation"]
                # if route_id not implemented in sale.order.line no problem
        else:
            lines = model.browse(self.env.context["active_ids"])
            try:
                route_ids = [l.route_id for l in lines]
                if route_ids:
                    pull_ids = [p.id for rt in route_ids for p in rt.pull_ids]
                    if pull_ids:
                        pull_ids = ProcurementRule.search(
                            [
                                ("id", "in", pull_ids),
                                ("active", "=", True),
                            ],
                            order="route_sequence asc, sequence asc",
                            limit=1,
                        )
                        pickings = {p.picking_type_id.warehouse_id.int_type_id for p in pull_ids}
                else:
                    pickings = {l.order_id.warehouse_id.int_type_id for l in lines}
            except AttributeError:
                self.env["stock.reservation"]
                # if route_id not implemented in sale.order.line no problem
        try:
            pickings
        except AttributeError:
            self.env["stock.reservation"]
            # prevent attributerror if no picking

        if len(pickings) == 1:
            return pickings.pop()
        elif len(pickings) > 1:
            raise exceptions.Warning(
                _(
                    """The lines have different picking types. Please reserve them
                    individually with the reserve button on each one."""
                )
            )

        return self.env["stock.reservation"]

    def _default_owner(self):
        """If sale_owner_stock_sourcing is installed, it adds an owner field
        on sale order lines. Use it.

        """
        model = self.env[self.env.context["active_model"]]
        if model._name == "sale.order":
            lines = model.browse(self.env.context["active_id"]).order_line
        else:
            lines = model.browse(self.env.context["active_ids"])

        try:
            owners = {l.stock_owner_id for l in lines}
        except AttributeError:
            return self.env["res.partner"]
            # module sale_owner_stock_sourcing not installed, fine

        if len(owners) == 1:
            return owners.pop()
        elif len(owners) > 1:
            raise exceptions.Warning(
                _(
                    """The lines have different owners. Please reserve them
                    individually with the reserve button on each one."""
                )
            )

        return self.env["res.partner"]

    location_id = fields.Many2one(
        "stock.location",
        "Source Location",
        required=True,
        default=_default_location_id,
    )
    location_dest_id = fields.Many2one(
        "stock.location",
        "Reservation Location",
        required=True,
        help="Location where the system will reserve the " "products.",
        default=_default_location_dest_id,
    )
    picking_type_id = fields.Many2one(
        "stock.picking.type",
        "Operation Type",
        required=True,
        help="Picking type for the operation.",
        default=_default_picking_type_id,
    )
    date_validity = fields.Date(
        "Validity Date",
        help="If a date is given, the reservations will be released "
        "at the end of the validity.",
    )
    note = fields.Text("Notes")
    owner_id = fields.Many2one("res.partner", "Stock Owner", default=_default_owner)

    def _prepare_stock_reservation(self, line):
        self.ensure_one()

        return {
            "product_id": line.product_id.id,
            "product_uom": line.product_uom.id,
            "product_uom_qty": line.product_uom_qty,
            "date_validity": self.date_validity,
            "name": "{} ({})".format(line.order_id.name, line.name),
            "location_id": self.location_id.id,
            "location_dest_id": self.location_dest_id.id,
            "picking_type_id": self.picking_type_id.id,
            "note": self.note,
            "price_unit": line.price_unit,
            "sale_line_id": line.id,
            "restrict_partner_id": self.owner_id.id,
        }

    def stock_reserve(self, line_ids):
        self.ensure_one()
        lines = self.env["sale.order.line"].browse(line_ids)
        for line in lines:
            if not line.is_stock_reservable:
                continue
            vals = self._prepare_stock_reservation(line)
            reserv = self.env["stock.reservation"].create(vals)
            reserv.reserve()
        return True

    def button_reserve(self):
        env = self.env
        self.ensure_one()
        close = {"type": "ir.actions.act_window_close"}
        active_model = env.context.get("active_model")
        active_ids = env.context.get("active_ids")
        if not (active_model and active_ids):
            return close

        if active_model == "sale.order":
            sales = env["sale.order"].browse(active_ids)
            line_ids = [line.id for sale in sales for line in sale.order_line]

        if active_model == "sale.order.line":
            line_ids = active_ids

        self.stock_reserve(line_ids)
        return close
