class BusinessRuleError(ValueError):
    pass


class ConflictError(BusinessRuleError):
    pass


class NotFoundError(BusinessRuleError):
    pass


class ForbiddenError(BusinessRuleError):
    pass
