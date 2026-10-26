/** Admin user management client — thin re-export of the typed
 * /admin/users endpoints in src/account/api.ts. */
export {
  addUser,
  deleteUser,
  listUsers,
  updateUser,
  type Role,
  type UserItem,
} from "../account/api";
